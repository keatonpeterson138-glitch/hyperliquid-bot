"""BacktestResult + metrics computation.

All metrics are pure functions of (equity_curve, trades) so the same
calculations are reused by walk-forward aggregation, Monte Carlo, and
parameter sweep ranking.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class Trade:
    entered_at: datetime
    exited_at: datetime
    symbol: str
    side: str           # 'long' | 'short'
    size_usd: float
    entry_price: float
    exit_price: float
    pnl_usd: float
    hold_bars: int = 0
    reason: str = ""


@dataclass
class BacktestResult:
    run_id: str
    symbol: str
    interval: str
    strategy: str
    config: dict[str, Any]
    starting_cash: float
    ending_equity: float
    equity_curve: pd.DataFrame        # columns: timestamp, equity, cash
    trades: list[Trade] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float]:
        return compute_metrics(
            self.equity_curve, self.trades, starting_cash=self.starting_cash
        )


def compute_metrics(
    equity_curve: pd.DataFrame,
    trades: list[Trade],
    *,
    starting_cash: float,
    bars_per_year: int = 252 * 24,  # hourly default; override per-interval
) -> dict[str, float]:
    ec = equity_curve.copy()
    if ec.empty:
        return _empty_metrics()
    ec = ec.sort_values("timestamp").reset_index(drop=True)

    ending = float(ec["equity"].iloc[-1])
    total_return_pct = (ending - starting_cash) / starting_cash * 100.0 if starting_cash > 0 else 0.0

    returns = ec["equity"].pct_change().fillna(0.0)
    # Sharpe — uses per-bar returns; annualize by sqrt(bars_per_year).
    if returns.std(ddof=0) > 0:
        sharpe = float(returns.mean() / returns.std(ddof=0) * math.sqrt(bars_per_year))
    else:
        sharpe = 0.0
    downside = returns[returns < 0]
    if len(downside) > 0 and downside.std(ddof=0) > 0:
        sortino = float(returns.mean() / downside.std(ddof=0) * math.sqrt(bars_per_year))
    else:
        sortino = 0.0

    # Max drawdown on equity curve.
    running_max = ec["equity"].cummax()
    drawdown = (ec["equity"] - running_max) / running_max
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
    max_dd_pct = max_dd * 100.0

    # CAGR — time span of equity curve.
    span_days = (ec["timestamp"].iloc[-1] - ec["timestamp"].iloc[0]).total_seconds() / 86400.0
    years = max(span_days / 365.25, 1e-9)
    if starting_cash > 0 and ending > 0:
        cagr = (ending / starting_cash) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0

    # Calmar = CAGR / |max_dd|.
    calmar = cagr / abs(max_dd) if abs(max_dd) > 1e-9 else 0.0

    # Trade-derived.
    wins = [t.pnl_usd for t in trades if t.pnl_usd > 0]
    losses = [t.pnl_usd for t in trades if t.pnl_usd < 0]
    trade_count = len(trades)
    win_rate = len(wins) / trade_count if trade_count > 0 else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss > 1e-9 else (math.inf if gross_win > 0 else 0.0)
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = -(gross_loss / len(losses)) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    avg_hold = sum(t.hold_bars for t in trades) / trade_count if trade_count > 0 else 0.0

    max_consec_losses = 0
    cur = 0
    for t in trades:
        if t.pnl_usd < 0:
            cur += 1
            max_consec_losses = max(max_consec_losses, cur)
        else:
            cur = 0

    pct_in_market = _pct_in_market(ec, trades)

    return {
        "total_return_pct": total_return_pct,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_dd_pct": max_dd_pct,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy_usd": expectancy,
        "avg_win_usd": avg_win,
        "avg_loss_usd": avg_loss,
        "max_consec_losses": float(max_consec_losses),
        "trade_count": float(trade_count),
        "avg_hold_bars": avg_hold,
        "pct_in_market": pct_in_market,
        "ending_equity_usd": ending,
    }


def _empty_metrics() -> dict[str, float]:
    return {
        "total_return_pct": 0.0, "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "max_dd_pct": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_usd": 0.0,
        "avg_win_usd": 0.0, "avg_loss_usd": 0.0, "max_consec_losses": 0.0,
        "trade_count": 0.0, "avg_hold_bars": 0.0, "pct_in_market": 0.0, "ending_equity_usd": 0.0,
    }


def _pct_in_market(ec: pd.DataFrame, trades: list[Trade]) -> float:
    if ec.empty or not trades:
        return 0.0
    total_span = (ec["timestamp"].iloc[-1] - ec["timestamp"].iloc[0]).total_seconds()
    if total_span <= 0:
        return 0.0
    in_market = sum(
        max(0.0, (t.exited_at - t.entered_at).total_seconds()) for t in trades
    )
    return min(1.0, in_market / total_span)
