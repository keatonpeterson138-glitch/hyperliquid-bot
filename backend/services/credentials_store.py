"""CredentialsStore — per-provider API keys + secrets for non-exchange
third parties. Hyperliquid trading keys still live in KeyVault.

Reads/writes are not encrypted at rest beyond SQLite file permissions —
this is fine for market-data API keys (Alpha Vantage, Polygon free tier
stuff). For anything that moves funds, use the vault wizard.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.db.app_db import AppDB

VALID_PROVIDERS = {
    "binance",
    "coinbase",
    "alpha_vantage",
    "polygon",
    "twelve_data",
    "cryptocompare",
    "coingecko",
    "messari",
    "telegram",
    "email",
    "rss",
    "other",
}


@dataclass
class Credential:
    id: str
    provider: str
    label: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def masked(self) -> Credential:
        """Returns a copy with api_key/secret masked. Used in every API
        response — the raw value only exists in-process while we use it."""
        return Credential(
            id=self.id,
            provider=self.provider,
            label=self.label,
            api_key=_mask(self.api_key),
            api_secret=_mask(self.api_secret),
            metadata=self.metadata,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


def _mask(v: str | None) -> str | None:
    if v is None or v == "":
        return v
    if len(v) <= 6:
        return "••••"
    return f"{v[:3]}…{v[-3:]}"


class CredentialsStore:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    # ── writes ────────────────────────────────────────────────────

    def create(
        self,
        *,
        provider: str,
        label: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Credential:
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Unknown provider: {provider!r}")
        cid = f"cred_{uuid.uuid4().hex[:12]}"
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO credentials(id, provider, label, api_key, api_secret, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cid, provider, label, api_key, api_secret,
                    json.dumps(metadata or {}),
                ),
            )
        got = self.get(cid)
        assert got is not None
        return got

    def update(
        self,
        cid: str,
        *,
        label: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Credential | None:
        cols: list[str] = []
        params: list[Any] = []
        if label is not None:
            cols.append("label = ?")
            params.append(label)
        if api_key is not None:
            cols.append("api_key = ?")
            params.append(api_key)
        if api_secret is not None:
            cols.append("api_secret = ?")
            params.append(api_secret)
        if metadata is not None:
            cols.append("metadata_json = ?")
            params.append(json.dumps(metadata))
        if not cols:
            return self.get(cid)
        cols.append("updated_at = ?")
        params.append(datetime.now(UTC))
        params.append(cid)
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE credentials SET {', '.join(cols)} WHERE id = ?", params)
        return self.get(cid)

    def delete(self, cid: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM credentials WHERE id = ?", (cid,))

    # ── reads ─────────────────────────────────────────────────────

    def get(self, cid: str) -> Credential | None:
        row = self.db.fetchone("SELECT * FROM credentials WHERE id = ?", (cid,))
        return _row_to_cred(row) if row else None

    def list(self, *, provider: str | None = None) -> list[Credential]:
        if provider:
            rows = self.db.fetchall(
                "SELECT * FROM credentials WHERE provider = ? ORDER BY updated_at DESC",
                (provider,),
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM credentials ORDER BY provider, updated_at DESC"
            )
        return [_row_to_cred(r) for r in rows]

    def first_for(self, provider: str) -> Credential | None:
        """Most-recently-updated credential for a provider. Used by
        backend services that only need 'the' key for that provider."""
        rows = self.list(provider=provider)
        return rows[0] if rows else None


def _row_to_cred(row: Any) -> Credential:
    return Credential(
        id=row["id"],
        provider=row["provider"],
        label=row["label"],
        api_key=row["api_key"],
        api_secret=row["api_secret"],
        metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
