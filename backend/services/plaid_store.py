"""PlaidStore — CRUD for ``plaid_items`` + ``plaid_accounts``.

One item = one institution the user linked. Items hold an
``access_token`` which persists indefinitely (until the user rotates
their bank password or we call ``item/remove``).

One account = one account within an item (e.g. a brokerage, a checking,
a 401k). The UI toggles ``tracked`` to control which ones feed the
Balances refresh.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.db.app_db import AppDB


@dataclass
class PlaidItem:
    id: str
    plaid_item_id: str
    access_token: str
    institution_id: str | None = None
    institution_name: str | None = None
    environment: str = "sandbox"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class PlaidAccount:
    id: str
    item_id: str
    plaid_account_id: str
    name: str | None = None
    official_name: str | None = None
    type: str | None = None
    subtype: str | None = None
    mask: str | None = None
    broker_label: str | None = None
    tracked: bool = True
    created_at: datetime | None = None
    # populated by joins — never stored
    institution_name: str | None = None


class PlaidStore:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    # ── items ─────────────────────────────────────────────────────

    def add_item(self, *, plaid_item_id: str, access_token: str,
                 institution_id: str | None = None,
                 institution_name: str | None = None,
                 environment: str = "sandbox") -> PlaidItem:
        iid = f"pli_{uuid.uuid4().hex[:12]}"
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO plaid_items(id, plaid_item_id, access_token,
                    institution_id, institution_name, environment)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(plaid_item_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    institution_id = COALESCE(excluded.institution_id, plaid_items.institution_id),
                    institution_name = COALESCE(excluded.institution_name, plaid_items.institution_name),
                    environment = excluded.environment,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (iid, plaid_item_id, access_token,
                 institution_id, institution_name, environment),
            )
        got = self.get_item_by_plaid_id(plaid_item_id)
        assert got is not None
        return got

    def list_items(self) -> list[PlaidItem]:
        rows = self.db.fetchall("SELECT * FROM plaid_items ORDER BY created_at DESC")
        return [_row_to_item(r) for r in rows]

    def get_item(self, iid: str) -> PlaidItem | None:
        row = self.db.fetchone("SELECT * FROM plaid_items WHERE id = ?", (iid,))
        return _row_to_item(row) if row else None

    def get_item_by_plaid_id(self, plaid_item_id: str) -> PlaidItem | None:
        row = self.db.fetchone("SELECT * FROM plaid_items WHERE plaid_item_id = ?", (plaid_item_id,))
        return _row_to_item(row) if row else None

    def delete_item(self, iid: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM plaid_items WHERE id = ?", (iid,))

    # ── accounts ──────────────────────────────────────────────────

    def upsert_account(self, *, item_id: str, plaid_account_id: str,
                       name: str | None = None, official_name: str | None = None,
                       type: str | None = None, subtype: str | None = None,
                       mask: str | None = None, broker_label: str | None = None,
                       tracked: bool = True) -> PlaidAccount:
        existing = self.db.fetchone(
            "SELECT id FROM plaid_accounts WHERE item_id = ? AND plaid_account_id = ?",
            (item_id, plaid_account_id),
        )
        if existing:
            aid = existing["id"]
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    UPDATE plaid_accounts SET
                        name = ?, official_name = ?, type = ?, subtype = ?,
                        mask = ?, broker_label = COALESCE(?, broker_label),
                        tracked = ?
                    WHERE id = ?
                    """,
                    (name, official_name, type, subtype, mask,
                     broker_label, 1 if tracked else 0, aid),
                )
        else:
            aid = f"pla_{uuid.uuid4().hex[:12]}"
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO plaid_accounts(id, item_id, plaid_account_id,
                        name, official_name, type, subtype, mask, broker_label, tracked)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (aid, item_id, plaid_account_id, name, official_name,
                     type, subtype, mask, broker_label, 1 if tracked else 0),
                )
        got = self.get_account(aid)
        assert got is not None
        return got

    def list_accounts(self) -> list[PlaidAccount]:
        rows = self.db.fetchall(
            """
            SELECT a.*, i.institution_name AS institution_name
            FROM plaid_accounts a
            LEFT JOIN plaid_items i ON i.id = a.item_id
            ORDER BY a.created_at ASC
            """,
        )
        return [_row_to_account(r) for r in rows]

    def list_tracked_accounts(self) -> list[PlaidAccount]:
        rows = self.db.fetchall(
            """
            SELECT a.*, i.institution_name AS institution_name
            FROM plaid_accounts a
            LEFT JOIN plaid_items i ON i.id = a.item_id
            WHERE a.tracked = 1
            ORDER BY a.created_at ASC
            """,
        )
        return [_row_to_account(r) for r in rows]

    def get_account(self, aid: str) -> PlaidAccount | None:
        row = self.db.fetchone(
            """
            SELECT a.*, i.institution_name AS institution_name
            FROM plaid_accounts a
            LEFT JOIN plaid_items i ON i.id = a.item_id
            WHERE a.id = ?
            """,
            (aid,),
        )
        return _row_to_account(row) if row else None

    def set_tracked(self, aid: str, tracked: bool) -> PlaidAccount | None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE plaid_accounts SET tracked = ? WHERE id = ?",
                (1 if tracked else 0, aid),
            )
        return self.get_account(aid)

    def set_broker_label(self, aid: str, broker_label: str) -> PlaidAccount | None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE plaid_accounts SET broker_label = ? WHERE id = ?",
                (broker_label, aid),
            )
        return self.get_account(aid)


def _row_to_item(row: Any) -> PlaidItem:
    return PlaidItem(
        id=row["id"],
        plaid_item_id=row["plaid_item_id"],
        access_token=row["access_token"],
        institution_id=row["institution_id"],
        institution_name=row["institution_name"],
        environment=row["environment"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_account(row: Any) -> PlaidAccount:
    acc = PlaidAccount(
        id=row["id"],
        item_id=row["item_id"],
        plaid_account_id=row["plaid_account_id"],
        name=row["name"],
        official_name=row["official_name"],
        type=row["type"],
        subtype=row["subtype"],
        mask=row["mask"],
        broker_label=row["broker_label"],
        tracked=bool(row["tracked"]),
        created_at=row["created_at"],
    )
    try:
        acc.institution_name = row["institution_name"]
    except (KeyError, IndexError):
        pass
    return acc
