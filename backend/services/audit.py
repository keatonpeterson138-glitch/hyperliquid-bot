"""AuditService — append-only event log for every order / modify / fill /
kill-switch / slot / risk event.

Backed by the ``audit_log`` SQLite table (whose triggers block UPDATE +
DELETE at the DB level — see migration 001_initial.sql). Every service
in Phase 2 writes here before / after mutating state.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.db.app_db import AppDB

logger = logging.getLogger(__name__)


# Known event types. Not strictly enforced — we accept free-form strings
# so custom callers don't need a PR to log a new event. This list
# documents what's canonical.
CANONICAL_EVENT_TYPES = frozenset(
    {
        # Orders
        "order_placed", "order_modified", "order_cancelled", "order_filled",
        # Positions
        "position_opened", "position_closed",
        # Slots
        "slot_created", "slot_updated", "slot_deleted",
        "slot_started", "slot_stopped",
        "decision_emitted", "decision_executed", "decision_rejected",
        # Risk
        "risk_breach", "shadow_divergence",
        # Key vault
        "key_store", "key_unlock", "key_lock", "key_wipe",
        # Kill switch
        "kill_switch_activated", "kill_switch_step", "kill_switch_reset",
        # Universe
        "universe_refreshed",
        # Config
        "config_change",
    }
)


@dataclass(frozen=True)
class AuditEvent:
    id: int
    ts: datetime
    event_type: str
    source: str
    slot_id: str | None = None
    strategy: str | None = None
    symbol: str | None = None
    side: str | None = None
    size_usd: float | None = None
    price: float | None = None
    reason: str | None = None
    exchange_response: dict[str, Any] | None = None


class AuditService:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    # ── Write ──────────────────────────────────────────────────────────────

    def log(
        self,
        event_type: str,
        *,
        source: str,
        slot_id: str | None = None,
        strategy: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        size_usd: float | None = None,
        price: float | None = None,
        reason: str | None = None,
        exchange_response: dict[str, Any] | None = None,
    ) -> int:
        """Append an audit row. Returns the new row id."""
        payload_json = json.dumps(exchange_response) if exchange_response else None
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log(
                    event_type, slot_id, strategy, symbol, side,
                    size_usd, price, reason, exchange_response_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    slot_id,
                    strategy,
                    symbol,
                    side,
                    size_usd,
                    price,
                    reason,
                    payload_json,
                    source,
                ),
            )
            return int(cursor.lastrowid or 0)

    # ── Read ───────────────────────────────────────────────────────────────

    def query(
        self,
        *,
        event_types: list[str] | None = None,
        symbol: str | None = None,
        slot_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[AuditEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(event_types)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if slot_id is not None:
            clauses.append("slot_id = ?")
            params.append(slot_id)
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("ts <= ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM audit_log{where} ORDER BY ts DESC, id DESC LIMIT ?"
        rows = self.db.fetchall(sql, tuple(params) + (limit,))
        return [_row_to_event(row) for row in rows]

    def count(self) -> int:
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM audit_log")
        return int(row["c"]) if row else 0


def _row_to_event(row: Any) -> AuditEvent:
    return AuditEvent(
        id=int(row["id"]),
        ts=_parse_ts(row["ts"]),
        event_type=row["event_type"],
        source=row["source"],
        slot_id=row["slot_id"],
        strategy=row["strategy"],
        symbol=row["symbol"],
        side=row["side"],
        size_usd=row["size_usd"],
        price=row["price"],
        reason=row["reason"],
        exchange_response=(
            json.loads(row["exchange_response_json"])
            if row["exchange_response_json"]
            else None
        ),
    )


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        # SQLite stores as ISO-like strings without tz — assume UTC.
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)
