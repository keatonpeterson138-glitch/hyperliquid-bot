"""/backtest — run a strategy backtest, parameter sweep, or Monte Carlo.

Results are held in memory by the service; persistent storage in
``data/backtests/*.parquet`` lands with Phase 11 polish.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.models.backtest import (
    BacktestRequest,
    BacktestResponse,
    EquityPoint,
    MonteCarloRequest,
    SweepRequest,
    SweepResponse,
    SweepRun,
    TradeOut,
)
from backend.services.backtest import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    monte_carlo_bootstrap,
    parameter_sweep,
)

router = APIRouter(tags=["backtest"])


class BacktestRegistry:
    """In-memory cache so /backtest/{id} can serve recent runs and
    Monte Carlo / UI overlays don't re-simulate needlessly."""

    def __init__(self) -> None:
        self._runs: dict[str, BacktestResult] = {}

    def put(self, r: BacktestResult) -> None:
        self._runs[r.run_id] = r

    def get(self, run_id: str) -> BacktestResult | None:
        return self._runs.get(run_id)

    def all(self) -> list[BacktestResult]:
        return list(self._runs.values())


def get_backtest_engine() -> BacktestEngine:
    raise HTTPException(status_code=503, detail="BacktestEngine not configured")


def get_backtest_registry() -> BacktestRegistry:
    raise HTTPException(status_code=503, detail="BacktestRegistry not configured")


EngineDep = Annotated[BacktestEngine, Depends(get_backtest_engine)]
RegistryDep = Annotated[BacktestRegistry, Depends(get_backtest_registry)]


def _to_response(r: BacktestResult) -> BacktestResponse:
    return BacktestResponse(
        run_id=r.run_id,
        symbol=r.symbol,
        interval=r.interval,
        strategy=r.strategy,
        config=r.config,
        starting_cash=r.starting_cash,
        ending_equity=r.ending_equity,
        metrics=r.metrics,
        trades=[
            TradeOut(
                entered_at=t.entered_at, exited_at=t.exited_at, symbol=t.symbol,
                side=t.side, size_usd=t.size_usd, entry_price=t.entry_price,
                exit_price=t.exit_price, pnl_usd=t.pnl_usd, hold_bars=t.hold_bars,
                reason=t.reason,
            )
            for t in r.trades
        ],
        equity_curve=[
            EquityPoint(timestamp=row["timestamp"], equity=row["equity"], cash=row["cash"])
            for _, row in r.equity_curve.iterrows()
        ],
    )


def _request_to_config(req: BacktestRequest) -> BacktestConfig:
    return BacktestConfig(
        symbol=req.symbol,
        interval=req.interval,
        strategy=req.strategy,
        strategy_params=req.strategy_params,
        starting_cash=req.starting_cash,
        size_usd=req.size_usd,
        leverage=req.leverage,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        slippage_bps=req.slippage_bps,
        fee_bps=req.fee_bps,
        funding_bps_per_bar=req.funding_bps_per_bar,
        bar_lookback=req.bar_lookback,
    )


@router.post("/backtest", response_model=BacktestResponse)
def run_backtest(
    req: BacktestRequest,
    engine: EngineDep,
    registry: RegistryDep,
) -> BacktestResponse:
    try:
        result = engine.run(_request_to_config(req), req.from_ts, req.to_ts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    registry.put(result)
    return _to_response(result)


@router.get("/backtest", response_model=list[BacktestResponse])
def list_backtests(registry: RegistryDep) -> list[BacktestResponse]:
    return [_to_response(r) for r in registry.all()]


@router.get("/backtest/{run_id}", response_model=BacktestResponse)
def get_backtest(run_id: str, registry: RegistryDep) -> BacktestResponse:
    r = registry.get(run_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Backtest not found: {run_id}")
    return _to_response(r)


@router.post("/backtest/sweep", response_model=SweepResponse)
def run_sweep(
    req: SweepRequest,
    engine: EngineDep,
    registry: RegistryDep,
) -> SweepResponse:
    try:
        pairs = parameter_sweep(
            engine,
            _request_to_config(req.base),
            req.base.from_ts,
            req.base.to_ts,
            grid=req.grid,
            rank_by=req.rank_by,
            max_runs=req.max_runs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runs = []
    for params, result in pairs:
        registry.put(result)
        runs.append(SweepRun(params=params, metrics=result.metrics, run_id=result.run_id))
    return SweepResponse(runs=runs)


@router.post("/backtest/monte-carlo")
def run_monte_carlo(
    req: MonteCarloRequest,
    registry: RegistryDep,
) -> dict[str, float]:
    result = registry.get(req.run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Backtest not found: {req.run_id}")
    return monte_carlo_bootstrap(result, n=req.n, seed=req.seed)
