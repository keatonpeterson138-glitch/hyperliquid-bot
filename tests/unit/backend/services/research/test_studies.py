"""Tests for research studies."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.services.research import (
    CorrelationMatrix,
    EventStudy,
    ReturnsSummary,
    SeasonalityHeatmap,
    VolatilityRegime,
    default_registry,
)


def _bars(symbol: str, n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    closes = 100 + rng.standard_normal(n).cumsum() * 0.5
    return pd.DataFrame({
        "timestamp": ts,
        "open": closes, "high": closes + 0.2, "low": closes - 0.2,
        "close": closes, "volume": rng.integers(100, 500, size=n).astype(float),
    })


def test_registry_lists_studies() -> None:
    reg = default_registry()
    names = {s["name"] for s in reg.list()}
    assert {"correlation_matrix", "seasonality_heatmap", "volatility_regime", "returns_summary", "event_study"} <= names


def test_correlation_matrix_returns_square(tmp_path) -> None:
    data = {"BTC": _bars("BTC", 100, seed=1), "ETH": _bars("ETH", 100, seed=2)}

    def cq(sym, interval, a, b):  # noqa: ARG001
        return data[sym]

    r = CorrelationMatrix().run(
        {"symbols": ["BTC", "ETH"], "interval": "1h",
         "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
        cq,
    )
    assert r.study == "correlation_matrix"
    assert "BTC" in r.data.columns and "ETH" in r.data.columns


def test_correlation_needs_two_symbols(tmp_path) -> None:
    def cq(sym, interval, a, b):  # noqa: ARG001
        return pd.DataFrame()

    with pytest.raises(ValueError):
        CorrelationMatrix().run(
            {"symbols": ["BTC"], "interval": "1h",
             "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
            cq,
        )


def test_seasonality_heatmap_rows(tmp_path) -> None:
    df = _bars("BTC", 24 * 14, seed=3)

    def cq(sym, interval, a, b):  # noqa: ARG001
        return df

    r = SeasonalityHeatmap().run(
        {"symbol": "BTC", "interval": "1h",
         "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
        cq,
    )
    assert not r.data.empty
    assert "dow" in r.data.columns


def test_volatility_regime(tmp_path) -> None:
    df = _bars("BTC", 200, seed=4)

    def cq(sym, interval, a, b):  # noqa: ARG001
        return df

    r = VolatilityRegime().run(
        {"symbol": "BTC", "interval": "1h", "window": 12,
         "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
        cq,
    )
    assert "vol" in r.data.columns
    assert r.data["vol"].dropna().iloc[-1] >= 0


def test_returns_summary(tmp_path) -> None:
    df = _bars("BTC", 500, seed=5)

    def cq(sym, interval, a, b):  # noqa: ARG001
        return df

    r = ReturnsSummary().run(
        {"symbol": "BTC", "interval": "1h",
         "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
        cq,
    )
    assert "mean" in r.data.columns
    assert "pos_fraction" in r.data.columns


def test_event_study_cohort() -> None:
    df = _bars("BTC", 500, seed=6)

    def cq(sym, interval, a, b):  # noqa: ARG001
        return df

    # Pick three event timestamps inside the range
    events = [
        df["timestamp"].iloc[100].isoformat(),
        df["timestamp"].iloc[200].isoformat(),
        df["timestamp"].iloc[300].isoformat(),
    ]
    r = EventStudy().run(
        {"symbol": "BTC", "interval": "1h", "window": 10, "events": events,
         "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
        cq,
    )
    # 20 bars (± 10) centered on each
    assert len(r.data) == 20
    assert "cum_return" in r.data.columns


def test_event_study_rejects_when_no_events_in_range() -> None:
    df = _bars("BTC", 500, seed=7)

    def cq(sym, interval, a, b):  # noqa: ARG001
        return df

    with pytest.raises(ValueError):
        EventStudy().run(
            {"symbol": "BTC", "interval": "1h", "window": 10, "events": [],
             "from_ts": "2024-01-01T00:00:00", "to_ts": "2024-02-01T00:00:00"},
            cq,
        )
