"""Pydantic models for /backtest."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    symbol: str
    interval: str
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    from_ts: datetime
    to_ts: datetime
    starting_cash: float = 10_000.0
    size_usd: float = 100.0
    leverage: int = 1
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    slippage_bps: float = 1.0
    fee_bps: float = 2.0
    funding_bps_per_bar: float = 0.0
    bar_lookback: int = 200


class TradeOut(BaseModel):
    entered_at: datetime
    exited_at: datetime
    symbol: str
    side: str
    size_usd: float
    entry_price: float
    exit_price: float
    pnl_usd: float
    hold_bars: int
    reason: str


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: float
    cash: float


class BacktestResponse(BaseModel):
    run_id: str
    symbol: str
    interval: str
    strategy: str
    config: dict[str, Any]
    starting_cash: float
    ending_equity: float
    metrics: dict[str, float]
    trades: list[TradeOut]
    equity_curve: list[EquityPoint]


class SweepRequest(BaseModel):
    base: BacktestRequest
    grid: dict[str, list[Any]]
    rank_by: str = "sharpe"
    max_runs: int | None = None


class SweepRun(BaseModel):
    params: dict[str, Any]
    metrics: dict[str, float]
    run_id: str


class SweepResponse(BaseModel):
    runs: list[SweepRun]


class MonteCarloRequest(BaseModel):
    run_id: str
    n: int = 500
    seed: int | None = 42
