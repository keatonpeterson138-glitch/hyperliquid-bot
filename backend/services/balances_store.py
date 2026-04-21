"""BalancesStore — per-broker equity snapshots.

Each row = one point-in-time value for a broker. The Balances page
pulls the most recent row per broker + summary across all. Brokers
with real APIs (Hyperliquid, Coinbase, Kraken) get auto-refreshed;
others are manual entries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.db.app_db import AppDB

SUPPORTED_BROKERS = (
    "hyperliquid", "coinbase", "kraken",
    "robinhood", "etrade", "fidelity", "schwab",
    "binance", "ibkr", "other",
)


@dataclass
class BalanceSnapshot:
    id: int | None
    broker: str
    asof: datetime
    equity_usd: float
    cash_usd: float | None = None
    buying_power: float | None = None
    unrealised_pnl: float | None = None
    realised_pnl_today: float | None = None
    source_note: str = "manual"
    raw: dict[str, Any] | None = None
    created_at: datetime | None = None


def _row_to_snap(row: Any) -> BalanceSnapshot:
    raw_json = row["raw_json"]
    return BalanceSnapshot(
        id=row["id"],
        broker=row["broker"],
        asof=row["asof"],
        equity_usd=float(row["equity_usd"]),
        cash_usd=row["cash_usd"],
        buying_power=row["buying_power"],
        unrealised_pnl=row["unrealised_pnl"],
        realised_pnl_today=row["realised_pnl_today"],
        source_note=row["source_note"] or "manual",
        raw=json.loads(raw_json) if raw_json else None,
        created_at=row["created_at"],
    )


class BalancesStore:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    def record(
        self,
        *,
        broker: str,
        equity_usd: float,
        cash_usd: float | None = None,
        buying_power: float | None = None,
        unrealised_pnl: float | None = None,
        realised_pnl_today: float | None = None,
        asof: datetime | None = None,
        source_note: str = "manual",
        raw: dict[str, Any] | None = None,
    ) -> BalanceSnapshot:
        if broker not in SUPPORTED_BROKERS:
            raise ValueError(f"Unknown broker: {broker}")
        ts = asof or datetime.now(UTC)
        raw_json = json.dumps(raw) if raw else None
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO balances(
                    broker, asof, equity_usd, cash_usd, buying_power,
                    unrealised_pnl, realised_pnl_today, source_note, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (broker, ts, equity_usd, cash_usd, buying_power,
                 unrealised_pnl, realised_pnl_today, source_note, raw_json),
            )
            bid = cur.lastrowid
        got = self.get(bid)
        assert got is not None
        return got

    def get(self, bid: int) -> BalanceSnapshot | None:
        row = self.db.fetchone("SELECT * FROM balances WHERE id = ?", (bid,))
        return _row_to_snap(row) if row else None

    def delete(self, bid: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM balances WHERE id = ?", (bid,))

    def latest_per_broker(self) -> list[BalanceSnapshot]:
        rows = self.db.fetchall(
            """
            SELECT * FROM balances b
            WHERE id = (
                SELECT id FROM balances b2
                WHERE b2.broker = b.broker
                ORDER BY asof DESC, id DESC LIMIT 1
            )
            ORDER BY broker
            """
        )
        return [_row_to_snap(r) for r in rows]

    def history(self, broker: str, limit: int = 100) -> list[BalanceSnapshot]:
        rows = self.db.fetchall(
            "SELECT * FROM balances WHERE broker = ? ORDER BY asof DESC LIMIT ?",
            (broker, limit),
        )
        return [_row_to_snap(r) for r in rows]
