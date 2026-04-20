"""Shared pytest fixtures — deterministic OHLCV builders for strategy tests.

Every fixture returns a DataFrame in the exact shape strategies consume:
columns `[open, high, low, close, volume]`, datetime index, UTC.
Shapes are tuned to cross strategy lookback thresholds cleanly so tests
stay deterministic and fast.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest


def make_ohlcv(
    close_prices: Sequence[float],
    *,
    high_pct: float = 0.002,
    low_pct: float = 0.002,
    start: datetime | None = None,
    step_minutes: int = 60,
) -> pd.DataFrame:
    """Build an OHLCV DataFrame from a sequence of close prices.

    Each bar's open = previous close (bar 0 uses its own close), high/low are
    small symmetric pct offsets around max/min of open/close, volume is 1000.
    """
    n = len(close_prices)
    if start is None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start + timedelta(minutes=step_minutes * i) for i in range(n)]
    closes = np.asarray(close_prices, dtype=float)
    opens = np.empty(n)
    opens[0] = closes[0]
    opens[1:] = closes[:-1]
    highs = np.maximum(closes, opens) * (1 + high_pct)
    lows = np.minimum(closes, opens) * (1 - low_pct)
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(n, 1000.0),
        },
        index=pd.DatetimeIndex(times),
    )


# ── EMA crossover scenarios ────────────────────────────────────────────────
#
# EMA(9) uses alpha=0.2; EMA(21) uses alpha~=0.0909. With a long flat run
# followed by a single pop on the last bar, fast EMA jumps further than slow
# EMA, so the last bar is exactly a bullish (or bearish) crossover:
#   fast_prev == slow_prev (both equal the flat price) → fast_prev <= slow_prev ✓
#   fast_curr  > slow_curr (fast moved more)            → bullish
# 32 bars clears the `slow_period + 10 = 31` minimum.


@pytest.fixture
def ema_bullish_cross_ohlcv() -> pd.DataFrame:
    """31 flat bars at 100 + 1 bar at 101 → bullish crossover on last bar."""
    closes = [100.0] * 31 + [101.0]
    return make_ohlcv(closes)


@pytest.fixture
def ema_bearish_cross_ohlcv() -> pd.DataFrame:
    """31 flat bars at 100 + 1 bar at 99 → bearish crossover on last bar."""
    closes = [100.0] * 31 + [99.0]
    return make_ohlcv(closes)


@pytest.fixture
def ema_no_cross_ohlcv() -> pd.DataFrame:
    """40 flat bars → no crossover possible (fast == slow everywhere)."""
    return make_ohlcv([100.0] * 40)


@pytest.fixture
def ema_insufficient_ohlcv() -> pd.DataFrame:
    """20 bars — below the 31-bar lookback minimum."""
    return make_ohlcv([100.0] * 20)


# ── RSI scenarios ──────────────────────────────────────────────────────────
#
# Strategy needs period + 10 = 24 bars. RSI is the ratio of rolling-mean gain
# to rolling-mean loss; a strictly-monotonic series forces one of the two to
# zero, which pins RSI to 0 (oversold) or 100 (overbought).


@pytest.fixture
def rsi_oversold_ohlcv() -> pd.DataFrame:
    """30 monotonically falling bars → RSI → 0 → oversold → LONG signal."""
    return make_ohlcv([100.0 - i for i in range(30)])


@pytest.fixture
def rsi_overbought_ohlcv() -> pd.DataFrame:
    """30 monotonically rising bars → RSI → 100 → overbought → SHORT signal."""
    return make_ohlcv([100.0 + i for i in range(30)])


@pytest.fixture
def rsi_neutral_ohlcv() -> pd.DataFrame:
    """Alternating up/down → RSI ~ 50 → neutral → HOLD."""
    closes = [100.0 + (i % 2) for i in range(30)]
    return make_ohlcv(closes)


@pytest.fixture
def rsi_insufficient_ohlcv() -> pd.DataFrame:
    """20 bars — below the 24-bar minimum."""
    return make_ohlcv([100.0] * 20)


# ── Breakout scenarios ─────────────────────────────────────────────────────
#
# Breakout uses lookback_period=20, requires 25 bars. Support/resistance are
# taken from iloc[-21:-1] (excludes the current candle). Buffer is tiny
# ((R-S) * 0.005 = 0.05 for a 10-wide range), so a small excess suffices.


@pytest.fixture
def breakout_bullish_ohlcv() -> pd.DataFrame:
    """24 rangebound bars (close=100, ±5 on highs/lows) + 1 bar closing at 107.

    Resistance from the prior 20 bars = ~105 (highs). Last bar closes above
    that plus buffer → bullish breakout.
    """
    base_closes = [100.0] * 24
    closes = base_closes + [107.0]
    # Build with wide high/low so the lookback has real support/resistance.
    df = make_ohlcv(closes, high_pct=0.05, low_pct=0.05)
    return df


@pytest.fixture
def breakout_bearish_ohlcv() -> pd.DataFrame:
    """24 rangebound bars + 1 bar closing at 93 → bearish breakout below support."""
    base_closes = [100.0] * 24
    closes = base_closes + [93.0]
    df = make_ohlcv(closes, high_pct=0.05, low_pct=0.05)
    return df


@pytest.fixture
def breakout_no_break_ohlcv() -> pd.DataFrame:
    """30 rangebound bars → no breakout."""
    return make_ohlcv([100.0] * 30, high_pct=0.05, low_pct=0.05)


@pytest.fixture
def breakout_insufficient_ohlcv() -> pd.DataFrame:
    """15 bars — below the 25-bar minimum."""
    return make_ohlcv([100.0] * 15, high_pct=0.05, low_pct=0.05)
