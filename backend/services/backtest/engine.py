"""BacktestEngine — bar-by-bar replay of the same TradeEngine that
runs live. Deterministic fills via ``ExchangeShim``; produces a
``BacktestResult`` with equity curve + trades + metrics.

Walk-forward, parameter sweep, and Monte Carlo are layered on top
without touching this file — see `walker.py`, `sweep.py`, `monte_carlo.py`.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from backend.services.backtest.result import BacktestResult, Trade
from backend.services.backtest.shim import ExchangeShim
from engine import Decision, DecisionAction, EngineContext, TradeEngine
from strategies.factory import get_strategy

logger = logging.getLogger(__name__)

DEFAULT_BARS_PER_YEAR = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


class _NoRiskGate:
    """Permissive risk gate for backtests — strategy signals go through."""

    def __init__(self, stop_loss_pct: float | None, take_profit_pct: float | None) -> None:
        self.sl = stop_loss_pct
        self.tp = take_profit_pct

    def can_trade(self) -> bool:
        return True

    def can_open_position(self, current_positions: int) -> bool:  # noqa: ARG002
        return True

    def check_position_exit(
        self, entry_price: float, current_price: float, is_long: bool
    ) -> str | None:
        pct = (current_price - entry_price) / entry_price * (1 if is_long else -1)
        if self.sl is not None and pct <= -self.sl:
            return "stop-loss"
        if self.tp is not None and pct >= self.tp:
            return "take-profit"
        return None


@dataclass
class BacktestConfig:
    symbol: str
    interval: str
    strategy: str
    strategy_params: dict[str, Any] = field(default_factory=dict)
    starting_cash: float = 10_000.0
    size_usd: float = 100.0
    leverage: int = 1
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    slippage_bps: float = 1.0
    fee_bps: float = 2.0
    funding_bps_per_bar: float = 0.0
    bar_lookback: int = 200


CandleQueryFn = Callable[[str, str, datetime, datetime], pd.DataFrame]


class BacktestEngine:
    def __init__(
        self,
        candle_query: CandleQueryFn,
        strategy_factory: Callable[[str, dict[str, Any]], Any] = get_strategy,
    ) -> None:
        self.candle_query = candle_query
        self.strategy_factory = strategy_factory

    def run(
        self,
        config: BacktestConfig,
        from_ts: datetime,
        to_ts: datetime,
    ) -> BacktestResult:
        bars_full = self.candle_query(config.symbol, config.interval, from_ts, to_ts)
        if bars_full is None or bars_full.empty:
            raise ValueError(
                f"No bars for {config.symbol}/{config.interval} {from_ts} → {to_ts}"
            )
        bars_full = bars_full.sort_values("timestamp").reset_index(drop=True)
        if "close" not in bars_full.columns:
            raise ValueError("candle query returned no 'close' column")

        strategy = self.strategy_factory(config.strategy, config.strategy_params)
        risk = _NoRiskGate(config.stop_loss_pct, config.take_profit_pct)
        engine = TradeEngine(strategy=strategy, risk=risk)

        shim = ExchangeShim(
            slippage_bps=config.slippage_bps,
            fee_bps=config.fee_bps,
            funding_bps_per_bar=config.funding_bps_per_bar,
        )
        shim.cash_usd = config.starting_cash

        equity_rows: list[dict] = []
        trades: list[Trade] = []
        open_pos_info: dict | None = None  # bookkeeping for Trade records

        for i in range(config.bar_lookback, len(bars_full)):
            window = bars_full.iloc[: i + 1].reset_index(drop=True)
            current_bar = window.iloc[-1]
            ts: datetime = _to_dt(current_bar["timestamp"])
            price = float(current_bar["close"])
            shim.set_clock(ts, price)

            position = shim.position
            current_pos_str = None
            entry_price = None
            if position is not None:
                current_pos_str = "LONG" if position.is_long else "SHORT"
                entry_price = position.entry_price

            ctx = EngineContext(
                symbol=config.symbol,
                current_price=price,
                candles_df=window,
                current_position=current_pos_str,
                entry_price=entry_price,
                open_position_count=int(position is not None),
            )

            decision = engine.decide(ctx)
            self._apply_decision(
                decision, shim, config, ts,
                open_pos_info_holder=(open_pos_info,),
                trades=trades,
            )
            # Rebind — we passed via tuple because python closures don't rebind dicts easily
            open_pos_info = self._open_pos_state(shim, open_pos_info, decision, ts, config.symbol, config.size_usd)

            equity_rows.append({
                "timestamp": ts, "equity": shim.equity(), "cash": shim.cash_usd,
            })

        ec = pd.DataFrame(equity_rows)
        bpy = DEFAULT_BARS_PER_YEAR.get(config.interval, 8_760)
        run_id = f"bt_{uuid.uuid4().hex[:12]}"

        result = BacktestResult(
            run_id=run_id,
            symbol=config.symbol,
            interval=config.interval,
            strategy=config.strategy,
            config={
                "strategy_params": config.strategy_params,
                "starting_cash": config.starting_cash,
                "size_usd": config.size_usd,
                "leverage": config.leverage,
                "stop_loss_pct": config.stop_loss_pct,
                "take_profit_pct": config.take_profit_pct,
                "slippage_bps": config.slippage_bps,
                "fee_bps": config.fee_bps,
                "funding_bps_per_bar": config.funding_bps_per_bar,
                "bars_per_year": bpy,
                "from_ts": from_ts.isoformat(),
                "to_ts": to_ts.isoformat(),
            },
            starting_cash=config.starting_cash,
            ending_equity=shim.equity(),
            equity_curve=ec,
            trades=trades,
        )
        return result

    # ── helpers ────────────────────────────────────────────────────────

    def _apply_decision(
        self,
        decision: Decision,
        shim: ExchangeShim,
        config: BacktestConfig,
        ts: datetime,
        *,
        open_pos_info_holder: tuple,
        trades: list[Trade],
    ) -> None:
        if decision.action is DecisionAction.HOLD:
            return

        pos_before = shim.position
        if decision.action is DecisionAction.OPEN_LONG:
            shim.place_market_order(config.symbol, is_buy=True, size_usd=config.size_usd, leverage=config.leverage)
        elif decision.action is DecisionAction.OPEN_SHORT:
            shim.place_market_order(config.symbol, is_buy=False, size_usd=config.size_usd, leverage=config.leverage)
        elif decision.action in (DecisionAction.CLOSE_LONG, DecisionAction.CLOSE_SHORT):
            if pos_before is not None:
                shim.close_position(config.symbol)

        # Record a completed trade if we just closed one.
        open_pos_info = open_pos_info_holder[0]
        if pos_before is not None and shim.position is None and open_pos_info is not None:
            last_fill = shim.fills[-1]
            trades.append(Trade(
                entered_at=open_pos_info["entered_at"],
                exited_at=ts,
                symbol=config.symbol,
                side="long" if pos_before.is_long else "short",
                size_usd=pos_before.size_usd,
                entry_price=pos_before.entry_price,
                exit_price=last_fill.price,
                pnl_usd=last_fill.realised_pnl_usd,
                hold_bars=open_pos_info.get("bar_span", 0) or 0,
                reason=decision.reason,
            ))

    def _open_pos_state(
        self,
        shim: ExchangeShim,
        prev: dict | None,
        decision: Decision,
        ts: datetime,
        symbol: str,
        size: float,
    ) -> dict | None:
        """Returns (possibly new) open-position metadata used for Trade records."""
        pos = shim.position
        if pos is None:
            return None
        # Opened this bar?
        if prev is None or (pos.entered_at == ts):
            return {"entered_at": pos.entered_at, "symbol": symbol, "size": size, "bar_span": 0, "bars_seen": 1}
        # Still open — bump bar span.
        prev["bars_seen"] = prev.get("bars_seen", 0) + 1
        prev["bar_span"] = prev["bars_seen"] - 1
        return prev


def _to_dt(value: Any) -> datetime:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().astimezone(UTC) if value.tzinfo else value.to_pydatetime().replace(tzinfo=UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value))
