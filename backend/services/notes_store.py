"""NotesStore — persistence for research/trading notes with attachments.

Notes are markdown bodies with optional embedded screenshots and widget
references. The markdown lives in SQLite; large binary attachments live
under ``data/notes/<note_id>/`` and the store just records their paths.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.db.app_db import AppDB


@dataclass
class NoteAttachment:
    id: int | None
    note_id: str
    path: str
    kind: str                    # 'screenshot' | 'file' | 'widget'
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Note:
    id: str
    title: str
    body_md: str
    tags: list[str] = field(default_factory=list)
    linked_layout_id: str | None = None
    linked_backtest_id: str | None = None
    attachments: list[NoteAttachment] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _row_to_note(row: Any, attachments: list[NoteAttachment]) -> Note:
    return Note(
        id=row["id"],
        title=row["title"],
        body_md=row["body_md"] or "",
        tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
        linked_layout_id=row["linked_layout_id"],
        linked_backtest_id=row["linked_backtest_id"],
        attachments=list(attachments),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_attachment(row: Any) -> NoteAttachment:
    return NoteAttachment(
        id=row["id"],
        note_id=row["note_id"],
        path=row["path"],
        kind=row["kind"],
        meta=json.loads(row["meta_json"]) if row["meta_json"] else {},
    )


class NotesStore:
    def __init__(self, db: AppDB, root: Path | str = "data/notes") -> None:
        self.db = db
        self.root = Path(root)

    def create(
        self,
        *,
        title: str,
        body_md: str = "",
        tags: list[str] | None = None,
        linked_layout_id: str | None = None,
        linked_backtest_id: str | None = None,
    ) -> Note:
        note_id = f"note_{uuid.uuid4().hex[:12]}"
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO notes(id, title, body_md, tags_json,
                    linked_layout_id, linked_backtest_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    note_id, title, body_md,
                    json.dumps(tags or []),
                    linked_layout_id,
                    linked_backtest_id,
                ),
            )
        return self.get(note_id)  # type: ignore[return-value]

    def update(self, note_id: str, fields: dict[str, Any]) -> Note | None:
        allowed = {"title", "body_md", "tags", "linked_layout_id", "linked_backtest_id"}
        cols: list[str] = []
        params: list[Any] = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "tags":
                cols.append("tags_json = ?")
                params.append(json.dumps(v or []))
            else:
                cols.append(f"{k} = ?")
                params.append(v)
        if not cols:
            return self.get(note_id)
        cols.append("updated_at = ?")
        params.append(datetime.now(UTC))
        params.append(note_id)
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE notes SET {', '.join(cols)} WHERE id = ?", params)
        return self.get(note_id)

    def delete(self, note_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def get(self, note_id: str) -> Note | None:
        row = self.db.fetchone("SELECT * FROM notes WHERE id = ?", (note_id,))
        if row is None:
            return None
        att_rows = self.db.fetchall(
            "SELECT * FROM note_attachments WHERE note_id = ? ORDER BY id",
            (note_id,),
        )
        return _row_to_note(row, [_row_to_attachment(r) for r in att_rows])

    def list(self, *, tag: str | None = None) -> list[Note]:
        rows = self.db.fetchall("SELECT * FROM notes ORDER BY updated_at DESC")
        out: list[Note] = []
        for row in rows:
            tags = json.loads(row["tags_json"]) if row["tags_json"] else []
            if tag is not None and tag not in tags:
                continue
            atts = self.db.fetchall(
                "SELECT * FROM note_attachments WHERE note_id = ? ORDER BY id",
                (row["id"],),
            )
            out.append(_row_to_note(row, [_row_to_attachment(a) for a in atts]))
        return out

    def add_attachment(
        self,
        note_id: str,
        *,
        path: str,
        kind: str,
        meta: dict[str, Any] | None = None,
    ) -> NoteAttachment:
        if kind not in {"screenshot", "file", "widget"}:
            raise ValueError(f"bad attachment kind: {kind}")
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO note_attachments(note_id, path, kind, meta_json)
                VALUES (?, ?, ?, ?)
                """,
                (note_id, path, kind, json.dumps(meta or {})),
            )
            att_id = cur.lastrowid
        return NoteAttachment(id=att_id, note_id=note_id, path=path, kind=kind, meta=meta or {})
