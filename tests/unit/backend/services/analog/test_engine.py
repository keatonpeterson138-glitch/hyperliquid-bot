"""Tests for analog pattern search."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.services.analog import (
    AnalogEngine,
    dtw_distance,
    lb_keogh_distance,
    zscore,
)


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _sinusoid_bars(n: int, period: int = 50, amp: float = 5.0, noise: float = 0.2, seed: int = 0) -> pd.DataFrame:
    rng = _rng(seed)
    t = np.arange(n)
    base = 100 + amp * np.sin(2 * np.pi * t / period) + rng.standard_normal(n) * noise
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=int(i)) for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts, "open": base, "high": base + 0.2,
        "low": base - 0.2, "close": base, "volume": np.full(n, 100.0),
    })


def test_zscore_normalises() -> None:
    x = np.array([1, 2, 3, 4, 5], dtype=float)
    z = zscore(x)
    assert abs(z.mean()) < 1e-9
    assert abs(z.std(ddof=0) - 1.0) < 1e-9


def test_zscore_flat_is_zero() -> None:
    z = zscore(np.full(10, 5.0))
    assert np.allclose(z, 0.0)


def test_dtw_identical_zero() -> None:
    x = np.linspace(0, 1, 50)
    assert dtw_distance(x, x) < 1e-9


def test_dtw_stretched_similar() -> None:
    x = np.sin(np.linspace(0, 2 * np.pi, 100))
    # slightly shifted version
    y = np.sin(np.linspace(0.1, 2 * np.pi + 0.1, 100))
    assert dtw_distance(x, y, window=20) < 2.0


def test_lb_keogh_lower_bounds_dtw() -> None:
    rng = _rng(1)
    a = rng.standard_normal(50)
    b = rng.standard_normal(50)
    lb = lb_keogh_distance(a, b, radius=5)
    full = dtw_distance(a, b, window=5)
    assert lb <= full + 1e-6


def test_analog_engine_finds_itself_as_best_match() -> None:
    bars = _sinusoid_bars(400, period=50)

    def cq(sym, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = AnalogEngine(candle_query=cq)
    q_end = bars["timestamp"].iloc[300]
    history_end = bars["timestamp"].iloc[280]  # history must *not* include the query window
    result = engine.query(
        symbol="BTC",
        interval="1h",
        from_ts=bars["timestamp"].iloc[0],
        to_ts=history_end,
        query_end_ts=q_end,
        window_len=40,
        forward_bars=20,
        top_k=5,
    )
    assert len(result.matches) > 0
    # Expect best distance to be reasonably small given sinusoidal structure
    assert result.matches[0].distance < 10.0
    # Forward distribution contains quantiles
    assert "p50" in result.forward_distribution


def test_analog_engine_insufficient_data_raises() -> None:
    bars = _sinusoid_bars(20)

    def cq(sym, interval, start, end):  # noqa: ARG001
        return bars

    engine = AnalogEngine(candle_query=cq)
    with pytest.raises(ValueError):
        engine.query(
            symbol="BTC",
            interval="1h",
            from_ts=bars["timestamp"].iloc[0],
            to_ts=bars["timestamp"].iloc[-1],
            query_end_ts=bars["timestamp"].iloc[-1],
            window_len=40,
        )
