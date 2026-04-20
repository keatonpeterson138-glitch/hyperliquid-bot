"""Tests for OutcomeSource — fake OutcomeTapeClient, no network."""
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from backend.services.sources.outcome_source import OutcomeSource


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_tape(self, market_id, start, end):
        self.calls.append((market_id, start, end))
        return self.rows


def test_empty_when_start_not_before_end() -> None:
    src = OutcomeSource(FakeClient([]))
    df = src.fetch_tape(
        "market_abc",
        datetime(2026, 1, 2, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert df.empty


def test_normalizes_to_canonical_schema_columns() -> None:
    raw = [
        {"t": 1730505600000, "p": 0.42, "v": 1000.0, "b": 0.41, "a": 0.43, "event_id": "btc_100k"},
        {"t": 1730505660000, "p": 0.44, "v": 500.0, "b": 0.43, "a": 0.45, "event_id": "btc_100k"},
    ]
    src = OutcomeSource(FakeClient(raw))
    df = src.fetch_tape(
        "market_abc",
        datetime(2024, 11, 1, tzinfo=UTC),
        datetime(2024, 12, 1, tzinfo=UTC),
    )
    assert set(df.columns) >= {
        "timestamp",
        "price",
        "volume",
        "implied_prob",
        "best_bid",
        "best_ask",
        "event_id",
        "source",
        "ingested_at",
    }
    assert len(df) == 2
    assert df["price"].tolist() == [0.42, 0.44]
    assert df["source"].iloc[0] == "hyperliquid-outcomes"


def test_empty_response_yields_empty_frame() -> None:
    src = OutcomeSource(FakeClient([]))
    df = src.fetch_tape(
        "market_abc",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert df.empty


def test_exception_returns_empty_frame() -> None:
    class BadClient:
        def fetch_tape(self, *a, **kw):
            raise RuntimeError("simulated")

    src = OutcomeSource(BadClient())
    df = src.fetch_tape(
        "market_abc",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert df.empty


def test_missing_bid_ask_uses_nan() -> None:
    raw = [{"t": 1730505600000, "p": 0.42, "v": 1000.0}]
    src = OutcomeSource(FakeClient(raw))
    df = src.fetch_tape(
        "market_abc",
        datetime(2024, 11, 1, tzinfo=UTC),
        datetime(2024, 12, 1, tzinfo=UTC),
    )
    assert len(df) == 1
    assert pd.isna(df["best_bid"].iloc[0])
    assert pd.isna(df["best_ask"].iloc[0])
