"""Walk-forward + parameter sweep + Monte Carlo helpers.

All three operate on top of ``BacktestEngine.run`` — they don't re-
implement the simulator.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from backend.services.backtest.engine import BacktestConfig, BacktestEngine
from backend.services.backtest.result import BacktestResult, Trade, compute_metrics


def walk_forward(
    engine: BacktestEngine,
    base_config: BacktestConfig,
    from_ts: datetime,
    to_ts: datetime,
    *,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
) -> list[BacktestResult]:
    """Rolling windows. Returns one BacktestResult per *test* window
    (train is whatever the strategy uses internally; we don't re-fit
    non-ML strategies, so train is effectively just warm-up lookback)."""
    step = step_days or test_days
    results: list[BacktestResult] = []
    cursor = from_ts + timedelta(days=train_days)
    while cursor + timedelta(days=test_days) <= to_ts:
        window_start = cursor - timedelta(days=train_days)  # include training history for lookback
        window_end = cursor + timedelta(days=test_days)
        results.append(engine.run(base_config, window_start, window_end))
        cursor += timedelta(days=step)
    return results


def aggregate_walk_forward(results: list[BacktestResult]) -> dict[str, float]:
    """Concatenate trades + equity curves, compute aggregate metrics."""
    if not results:
        return {}
    all_trades: list[Trade] = []
    for r in results:
        all_trades.extend(r.trades)
    import pandas as pd
    ec = pd.concat([r.equity_curve for r in results], ignore_index=True)
    ec = ec.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
    return compute_metrics(ec, all_trades, starting_cash=results[0].starting_cash)


def parameter_sweep(
    engine: BacktestEngine,
    base_config: BacktestConfig,
    from_ts: datetime,
    to_ts: datetime,
    *,
    grid: dict[str, list[Any]],
    rank_by: str = "sharpe",
    max_runs: int | None = None,
) -> list[tuple[dict[str, Any], BacktestResult]]:
    """Full grid search over ``grid`` — keys are ``strategy_params`` field
    names. Returns (params, result) pairs sorted descending by ``rank_by``
    metric."""
    keys = list(grid.keys())
    combos = list(itertools.product(*(grid[k] for k in keys)))
    if max_runs is not None and len(combos) > max_runs:
        combos = combos[:max_runs]

    pairs: list[tuple[dict[str, Any], BacktestResult]] = []
    for combo in combos:
        params = dict(zip(keys, combo, strict=False))
        merged = {**base_config.strategy_params, **params}
        cfg = replace(base_config, strategy_params=merged)
        result = engine.run(cfg, from_ts, to_ts)
        pairs.append((params, result))

    pairs.sort(key=lambda pr: pr[1].metrics.get(rank_by, 0.0), reverse=True)
    return pairs


def monte_carlo_bootstrap(
    result: BacktestResult,
    *,
    n: int = 500,
    seed: int | None = 42,
) -> dict[str, float]:
    """Shuffle the trade order N times; compute 95% CI on max_dd + ending_equity.

    Doesn't re-simulate — just permutes the trade sequence. Same total
    return; different path, different drawdown.
    """
    if not result.trades:
        return {}
    rng = random.Random(seed)
    dds: list[float] = []
    endings: list[float] = []
    pnls = [t.pnl_usd for t in result.trades]
    starting = result.starting_cash
    for _ in range(n):
        order = list(pnls)
        rng.shuffle(order)
        equity = starting
        peak = equity
        worst_dd = 0.0
        for p in order:
            equity += p
            peak = max(peak, equity)
            dd = (equity - peak) / peak if peak > 0 else 0.0
            worst_dd = min(worst_dd, dd)
        dds.append(worst_dd * 100.0)
        endings.append(equity)
    dds.sort()
    endings.sort()

    def pct(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        idx = int(round(q * (len(values) - 1)))
        return values[idx]

    return {
        "mc_n": float(n),
        "mc_dd_p5_pct": pct(dds, 0.05),
        "mc_dd_p50_pct": pct(dds, 0.50),
        "mc_dd_p95_pct": pct(dds, 0.95),
        "mc_ending_p5_usd": pct(endings, 0.05),
        "mc_ending_p50_usd": pct(endings, 0.50),
        "mc_ending_p95_usd": pct(endings, 0.95),
    }
