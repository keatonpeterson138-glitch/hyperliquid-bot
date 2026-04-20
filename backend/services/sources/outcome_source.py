"""Outcome tape source — adapter between ``core/outcome_client`` and the
outcome Parquet writer.

Phase 6 wires this to a live WebSocket feed. Phase 1 ships the offline
API surface so the UI + researcher can pre-seed tapes and query them
from the moment HIP-4 hits mainnet.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

import pandas as pd

from backend.db.schemas import OUTCOME_TAPE_SCHEMA

logger = logging.getLogger(__name__)


class OutcomeTapeClient(Protocol):
    """Subset of ``core.outcome_client.OutcomeClient`` we use here.

    Accepts an injected fake during tests — no need to construct the
    real client against a live node.
    """

    def fetch_tape(
        self, market_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]: ...


class OutcomeSource:
    """Fetches HIP-4 outcome ticks and normalizes them to canonical rows."""

    name = "hyperliquid-outcomes"

    def __init__(self, client: OutcomeTapeClient) -> None:
        self.client = client

    def fetch_tape(
        self, market_id: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if start >= end:
            return _empty_tape()

        try:
            raw = self.client.fetch_tape(market_id, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.error("Outcome tape fetch failed for %s: %s", market_id, exc)
            return _empty_tape()

        if not raw:
            return _empty_tape()

        return _normalize_outcome_ticks(raw, source=self.name)


def _empty_tape() -> pd.DataFrame:
    cols = [f.name for f in OUTCOME_TAPE_SCHEMA]
    df = pd.DataFrame({c: [] for c in cols})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["ingested_at"] = pd.to_datetime(df["ingested_at"], utc=True)
    return df


def _normalize_outcome_ticks(raw: list[dict[str, Any]], *, source: str) -> pd.DataFrame:
    """Convert a list of outcome ticks to the canonical OUTCOME_TAPE_SCHEMA frame.

    Expected keys per raw dict: ``t`` (ms), ``p`` (price), ``v`` (volume),
    ``b`` (best bid), ``a`` (best ask), ``event_id`` (optional).
    Missing fields are filled with NaN / None.
    """
    rows = []
    for item in raw:
        ts_ms = int(item["t"])
        price = float(item["p"])
        rows.append(
            {
                "timestamp": pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
                "price": price,
                "volume": float(item.get("v", 0.0)),
                "implied_prob": float(item.get("implied_prob", price)),
                "best_bid": float(item["b"]) if "b" in item else float("nan"),
                "best_ask": float(item["a"]) if "a" in item else float("nan"),
                "event_id": item.get("event_id"),
                "source": source,
                "ingested_at": pd.Timestamp.now(tz="UTC"),
            }
        )
    return pd.DataFrame(rows)
