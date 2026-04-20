"""Tests for BacktestEngine + ExchangeShim + metrics."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.services.backtest import (
    BacktestConfig,
    BacktestEngine,
    ExchangeShim,
    compute_metrics,
    monte_carlo_bootstrap,
    parameter_sweep,
    walk_forward,
)
from strategies.base import BaseStrategy, Signal, SignalType


def _make_bars(n: int, start_price: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    # deterministic seed
    rng = np.random.default_rng(42)
    noise = rng.standard_normal(n) * 0.2
    closes = np.array([start_price + i * trend + noise[i] for i in range(n)])
    closes = np.clip(closes, 1.0, None)
    highs = closes + np.abs(rng.standard_normal(n)) * 0.1
    lows = closes - np.abs(rng.standard_normal(n)) * 0.1
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    vols = (rng.integers(100, 1000, size=n)).astype(float)
    return pd.DataFrame({
        "timestamp": ts, "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols,
    })


class _ScriptedStrategy(BaseStrategy):
    """Emits a fixed sequence of signals, cycling — for deterministic tests."""

    def __init__(self, signals: list[SignalType]) -> None:
        super().__init__(name="scripted")
        self._signals = signals
        self._i = 0

    def analyze(self, df: pd.DataFrame, current_position: str | None) -> Signal:  # noqa: ARG002
        s = self._signals[self._i % len(self._signals)]
        self._i += 1
        return Signal(signal_type=s, strength=1.0, reason="scripted")


def _factory(signals):
    def factory(name: str, params: dict) -> BaseStrategy:  # noqa: ARG001
        return _ScriptedStrategy(signals)
    return factory


def test_shim_long_roundtrip_positive_pnl() -> None:
    shim = ExchangeShim(slippage_bps=0.0, fee_bps=0.0)
    shim.set_clock(datetime(2024, 1, 1, tzinfo=UTC), 100.0)
    shim.place_market_order("BTC", is_buy=True, size_usd=100.0, leverage=1)
    shim.set_clock(datetime(2024, 1, 2, tzinfo=UTC), 110.0)
    shim.close_position("BTC")
    # 10% move on a $100 long = $10 PnL
    assert abs(shim.cash_usd - 10.0) < 1e-6
    assert shim.position is None


def test_shim_short_roundtrip_positive_pnl_on_drop() -> None:
    shim = ExchangeShim(slippage_bps=0.0, fee_bps=0.0)
    shim.set_clock(datetime(2024, 1, 1, tzinfo=UTC), 100.0)
    shim.place_market_order("BTC", is_buy=False, size_usd=100.0, leverage=1)
    shim.set_clock(datetime(2024, 1, 2, tzinfo=UTC), 90.0)
    shim.close_position("BTC")
    assert abs(shim.cash_usd - 10.0) < 1e-6


def test_engine_runs_to_completion() -> None:
    bars = _make_bars(250, trend=0.5)

    def candle_query(symbol, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = BacktestEngine(
        candle_query=candle_query,
        strategy_factory=_factory([
            SignalType.LONG, *[SignalType.HOLD] * 10,
            SignalType.CLOSE_LONG, *[SignalType.HOLD] * 10,
        ]),
    )
    cfg = BacktestConfig(
        symbol="BTC", interval="1h", strategy="ema_crossover",
        starting_cash=10_000, size_usd=100.0, bar_lookback=50,
    )
    result = engine.run(cfg, bars["timestamp"].iloc[0], bars["timestamp"].iloc[-1])
    assert not result.equity_curve.empty
    assert result.run_id.startswith("bt_")
    # with an uptrend + scripted long-then-close, expect >= 1 completed trade
    assert len(result.trades) >= 1


def test_metrics_shape_and_nonnegative() -> None:
    bars = _make_bars(150, trend=0.3)

    def candle_query(symbol, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = BacktestEngine(
        candle_query=candle_query,
        strategy_factory=_factory([SignalType.LONG, SignalType.HOLD, SignalType.CLOSE_LONG]),
    )
    cfg = BacktestConfig(symbol="BTC", interval="1h", strategy="x", bar_lookback=20)
    r = engine.run(cfg, bars["timestamp"].iloc[0], bars["timestamp"].iloc[-1])
    m = r.metrics
    for key in [
        "total_return_pct", "sharpe", "sortino", "calmar", "max_dd_pct",
        "win_rate", "profit_factor", "trade_count", "avg_hold_bars",
        "pct_in_market", "ending_equity_usd",
    ]:
        assert key in m
    assert m["trade_count"] >= 1


def test_deterministic_same_seed_same_result() -> None:
    """Same inputs → same equity curve byte-for-byte."""
    bars = _make_bars(100, trend=0.2)

    def candle_query(symbol, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    factory = _factory([SignalType.LONG, SignalType.HOLD, SignalType.CLOSE_LONG])
    e1 = BacktestEngine(candle_query, strategy_factory=factory)
    e2 = BacktestEngine(candle_query, strategy_factory=factory)
    cfg = BacktestConfig(symbol="BTC", interval="1h", strategy="x", bar_lookback=10)
    r1 = e1.run(cfg, bars["timestamp"].iloc[0], bars["timestamp"].iloc[-1])
    r2 = e2.run(cfg, bars["timestamp"].iloc[0], bars["timestamp"].iloc[-1])
    pd.testing.assert_frame_equal(
        r1.equity_curve.reset_index(drop=True),
        r2.equity_curve.reset_index(drop=True),
    )


def test_empty_data_raises() -> None:
    def empty(*_a, **_k):
        return pd.DataFrame()

    engine = BacktestEngine(candle_query=empty)
    cfg = BacktestConfig(symbol="BTC", interval="1h", strategy="x")
    with pytest.raises(ValueError):
        engine.run(cfg, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))


def test_walk_forward_produces_multiple_results() -> None:
    bars = _make_bars(480, trend=0.1)  # 20 days hourly

    def candle_query(symbol, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = BacktestEngine(
        candle_query, strategy_factory=_factory([SignalType.HOLD]),
    )
    cfg = BacktestConfig(symbol="BTC", interval="1h", strategy="x", bar_lookback=10)
    results = walk_forward(
        engine, cfg,
        bars["timestamp"].iloc[0], bars["timestamp"].iloc[-1],
        train_days=3, test_days=3, step_days=3,
    )
    assert len(results) >= 2


def test_monte_carlo_returns_percentiles() -> None:
    from backend.services.backtest.result import BacktestResult, Trade
    trades = [
        Trade(
            entered_at=datetime(2024, 1, 1, tzinfo=UTC),
            exited_at=datetime(2024, 1, 2, tzinfo=UTC),
            symbol="BTC", side="long", size_usd=100,
            entry_price=100, exit_price=100 + p, pnl_usd=float(p),
        )
        for p in [10, -5, 8, -3, 12, -7, 4, -2]
    ]
    result = BacktestResult(
        run_id="bt_test",
        symbol="BTC",
        interval="1h",
        strategy="x",
        config={},
        starting_cash=10_000,
        ending_equity=10_000 + sum(t.pnl_usd for t in trades),
        equity_curve=pd.DataFrame(),
        trades=trades,
    )
    mc = monte_carlo_bootstrap(result, n=200, seed=7)
    assert mc["mc_n"] == 200
    assert mc["mc_dd_p5_pct"] <= mc["mc_dd_p50_pct"] <= mc["mc_dd_p95_pct"]


def test_parameter_sweep_ranks_by_metric() -> None:
    bars = _make_bars(150, trend=0.2)

    def candle_query(symbol, interval, start, end):  # noqa: ARG001
        mask = (bars["timestamp"] >= start) & (bars["timestamp"] <= end)
        return bars.loc[mask]

    engine = BacktestEngine(
        candle_query,
        strategy_factory=_factory([SignalType.LONG, SignalType.HOLD, SignalType.CLOSE_LONG]),
    )
    cfg = BacktestConfig(symbol="BTC", interval="1h", strategy="x", bar_lookback=10)
    pairs = parameter_sweep(
        engine, cfg,
        bars["timestamp"].iloc[0], bars["timestamp"].iloc[-1],
        grid={"fast": [5, 10, 20]},
        rank_by="sharpe",
    )
    assert len(pairs) == 3
    # Sorted descending by sharpe
    assert pairs[0][1].metrics["sharpe"] >= pairs[-1][1].metrics["sharpe"]


def test_compute_metrics_empty() -> None:
    m = compute_metrics(pd.DataFrame(), [], starting_cash=10_000)
    assert m["total_return_pct"] == 0.0
    assert m["trade_count"] == 0.0
