"""MarkupStore — persistence for chart drawings.

Phase 5 ships the CRUD surface. Phase 5.5 (deferred) wires the
drag-to-modify path that translates ``state='active'`` markups into
real exchange orders.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.db.app_db import AppDB


@dataclass
class Markup:
    id: str
    layout_id: str | None
    symbol: str
    interval: str | None
    tool_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    style: dict[str, Any] = field(default_factory=dict)
    z: int = 0
    locked: bool = False
    hidden: bool = False
    state: str = "draft"
    order_id: str | None = None


def _row_to_markup(row: Any) -> Markup:
    return Markup(
        id=row["id"],
        layout_id=row["layout_id"],
        symbol=row["symbol"],
        interval=row["interval"],
        tool_id=row["tool_id"],
        payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
        style=json.loads(row["style_json"]) if row["style_json"] else {},
        z=row["z"] or 0,
        locked=bool(row["locked"]),
        hidden=bool(row["hidden"]),
        state=row["state"] or "draft",
        order_id=row["order_id"],
    )


class MarkupStore:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    def list(
        self,
        *,
        symbol: str | None = None,
        interval: str | None = None,
        layout_id: str | None = None,
    ) -> list[Markup]:
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if interval:
            clauses.append("interval = ?")
            params.append(interval)
        if layout_id:
            clauses.append("layout_id = ?")
            params.append(layout_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.fetchall(
            f"SELECT * FROM markups{where} ORDER BY z, id", tuple(params)
        )
        return [_row_to_markup(r) for r in rows]

    def get(self, markup_id: str) -> Markup | None:
        row = self.db.fetchone("SELECT * FROM markups WHERE id = ?", (markup_id,))
        return _row_to_markup(row) if row else None

    def create(
        self,
        *,
        symbol: str,
        tool_id: str,
        payload: dict[str, Any],
        interval: str | None = None,
        layout_id: str | None = None,
        style: dict[str, Any] | None = None,
        z: int = 0,
    ) -> Markup:
        markup_id = f"markup_{uuid.uuid4().hex[:12]}"
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO markups(id, layout_id, symbol, interval, tool_id,
                    payload_json, style_json, z, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')
                """,
                (
                    markup_id,
                    layout_id,
                    symbol,
                    interval,
                    tool_id,
                    json.dumps(payload),
                    json.dumps(style or {}),
                    z,
                ),
            )
        return self.get(markup_id)  # type: ignore[return-value]

    def update(self, markup_id: str, fields: dict[str, Any]) -> Markup | None:
        if not fields:
            return self.get(markup_id)
        translation = {"payload": "payload_json", "style": "style_json"}
        col_values: dict[str, Any] = {}
        for k, v in fields.items():
            col = translation.get(k, k)
            if k in ("payload", "style"):
                v = json.dumps(v or {})
            elif isinstance(v, bool):
                v = int(v)
            col_values[col] = v
        col_values["updated_at"] = datetime.now(UTC)
        cols = ", ".join(f"{k} = ?" for k in col_values)
        params = list(col_values.values()) + [markup_id]
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE markups SET {cols} WHERE id = ?", params)
        return self.get(markup_id)

    def delete(self, markup_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM markups WHERE id = ?", (markup_id,))
