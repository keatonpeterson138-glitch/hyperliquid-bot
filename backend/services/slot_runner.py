"""SlotRunner — runs one slot's decision loop.

Pure-function ``tick()``: assemble context → run engine → execute
actionable decisions → audit + persist state. No threading, no
scheduling — those are the orchestrator's job (``TradeEngineService``).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.order_executor import (
    ExchangeClient,
    ExecutionResult,
    OrderExecutor,
)
from backend.services.slot_repository import SlotRepository
from backend.services.sources.base import interval_to_timedelta
from engine import Decision, DecisionAction, EngineContext, TradeEngine

logger = logging.getLogger(__name__)


# Number of bars we keep in the engine context. 200 is plenty for every
# packaged strategy (longest is breakout's lookback_period=20).
DEFAULT_BAR_LOOKBACK = 200


CandleQueryFn = Callable[[str, str, datetime, datetime], pd.DataFrame]


class SlotRiskAdapter:
    """Adapt a Slot's risk-relevant fields to engine.RiskGate."""

    def __init__(self, slot: Slot, *, max_open_positions: int = 5) -> None:
        self.slot = slot
        self.max_open_positions = max_open_positions

    def can_trade(self) -> bool:
        # Daily-loss-limit lives in the per-slot SLOT_* envelope in v1.
        # AggregateExposure cap is enforced separately by the orchestrator (P2.7).
        return True

    def can_open_position(self, current_positions: int) -> bool:
        return current_positions < self.max_open_positions

    def check_position_exit(
        self, entry_price: float, current_price: float, is_long: bool
    ) -> str | None:
        if entry_price <= 0:
            return None
        change = (current_price - entry_price) / entry_price
        if not is_long:
            change = -change
        sl = self.slot.stop_loss_pct
        tp = self.slot.take_profit_pct
        if sl is not None and change <= -sl / 100.0:
            return "stop_loss"
        if tp is not None and change >= tp / 100.0:
            return "take_profit"
        return None


@dataclass
class SlotRunner:
    repo: SlotRepository
    audit: AuditService
    exchange: ExchangeClient
    candle_query: CandleQueryFn
    strategy_factory: Callable[[str, dict[str, Any]], Any]
    executor: OrderExecutor = None  # type: ignore[assignment]
    on_event: Callable[[dict[str, Any]], None] | None = None
    bar_lookback: int = DEFAULT_BAR_LOOKBACK

    def __post_init__(self) -> None:
        if self.executor is None:
            self.executor = OrderExecutor()

    def tick(self, slot: Slot, *, now: datetime | None = None) -> Decision:
        now = now or datetime.now(UTC)

        if not slot.enabled:
            return Decision(DecisionAction.HOLD, reason="slot disabled")

        # 1. Live current price.
        try:
            current_price = self.exchange.get_market_price(slot.symbol)
        except Exception as exc:  # noqa: BLE001
            self.audit.log(
                "decision_rejected",
                source="slot_runner",
                slot_id=slot.id,
                strategy=slot.strategy,
                symbol=slot.symbol,
                reason=f"price fetch failed: {exc}",
            )
            return Decision(DecisionAction.HOLD, reason="price unavailable")

        if current_price is None:
            return Decision(DecisionAction.HOLD, reason="price unavailable")

        # 2. Candle window.
        if slot.interval is None:
            return Decision(DecisionAction.HOLD, reason="slot has no interval")
        try:
            bar_td = interval_to_timedelta(slot.interval)
        except ValueError:
            return Decision(DecisionAction.HOLD, reason=f"unknown interval: {slot.interval}")
        candles_start = now - bar_td * self.bar_lookback
        candles_df = self.candle_query(slot.symbol, slot.interval, candles_start, now)

        # 3. Position state.
        state = self.repo.get_state(slot.id)
        current_position = state.current_position if state else None
        entry_price = state.entry_price if state else None

        # 4. Build engine context.
        ctx = EngineContext(
            symbol=slot.symbol,
            current_price=float(current_price),
            candles_df=candles_df,
            current_position=current_position,
            entry_price=entry_price,
            open_position_count=int(bool(current_position)),
        )

        # 5. Pure decision via the engine.
        try:
            strategy = self.strategy_factory(slot.strategy, slot.strategy_params)
        except Exception as exc:  # noqa: BLE001
            self.audit.log(
                "decision_rejected",
                source="slot_runner",
                slot_id=slot.id,
                reason=f"strategy construction failed: {exc}",
            )
            return Decision(DecisionAction.HOLD, reason="strategy unavailable")

        risk = SlotRiskAdapter(slot)
        engine = TradeEngine(strategy=strategy, risk=risk)
        decision = engine.decide(ctx)

        # 6. Audit decision.
        self.audit.log(
            "decision_emitted",
            source="slot_runner",
            slot_id=slot.id,
            strategy=slot.strategy,
            symbol=slot.symbol,
            reason=decision.reason or decision.action.value,
        )
        self._emit("decision", slot, decision)

        # 7. Execute if actionable.
        execution: ExecutionResult | None = None
        if decision.is_actionable:
            execution = self.executor.execute(decision, slot, self.exchange)
            if execution.success:
                self.audit.log(
                    "decision_executed",
                    source="slot_runner",
                    slot_id=slot.id,
                    strategy=slot.strategy,
                    symbol=slot.symbol,
                    side=_side_for(decision),
                    size_usd=slot.size_usd,
                    price=execution.fill_price,
                    reason=decision.reason,
                    exchange_response=execution.raw_response,
                )
                self._update_position_state(slot, decision, execution, current_price)
            else:
                self.audit.log(
                    "decision_rejected",
                    source="slot_runner",
                    slot_id=slot.id,
                    strategy=slot.strategy,
                    symbol=slot.symbol,
                    reason=execution.error or "execution failed",
                )
        elif decision.rejection:
            self.audit.log(
                "decision_rejected",
                source="slot_runner",
                slot_id=slot.id,
                strategy=slot.strategy,
                symbol=slot.symbol,
                reason=decision.rejection,
            )

        # 8. Always touch slot_state.
        self.repo.upsert_state(
            slot.id,
            last_tick_at=now,
            last_decision_action=decision.action.value,
        )
        return decision

    def _update_position_state(
        self,
        slot: Slot,
        decision: Decision,
        execution: ExecutionResult,
        current_price: float,
    ) -> None:
        action = decision.action
        if action in (DecisionAction.OPEN_LONG, DecisionAction.OPEN_SHORT):
            self.repo.upsert_state(
                slot.id,
                current_position="LONG" if action is DecisionAction.OPEN_LONG else "SHORT",
                entry_price=execution.fill_price or current_price,
                position_size_usd=slot.size_usd,
                open_order_ids=([execution.order_id] if execution.order_id else []),
            )
        elif action in (DecisionAction.CLOSE_LONG, DecisionAction.CLOSE_SHORT):
            self.repo.upsert_state(
                slot.id,
                current_position=None,
                entry_price=None,
                position_size_usd=None,
                open_order_ids=[],
            )

    def _emit(self, kind: str, slot: Slot, decision: Decision) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(
                {
                    "type": kind,
                    "slot_id": slot.id,
                    "symbol": slot.symbol,
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "strength": decision.strength,
                    "rejection": decision.rejection,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("on_event callback raised: %s", exc)


def _side_for(decision: Decision) -> str | None:
    if decision.action in (DecisionAction.OPEN_LONG, DecisionAction.CLOSE_LONG):
        return "LONG"
    if decision.action in (DecisionAction.OPEN_SHORT, DecisionAction.CLOSE_SHORT):
        return "SHORT"
    return None


# Convenience for tests / console: bar_lookback defaults to a generous 200.
__all__ = ["SlotRunner", "SlotRiskAdapter", "DEFAULT_BAR_LOOKBACK", "CandleQueryFn"]


# Silence unused-import when `bar_td` only used in conditional code paths.
_BAR_HELPER = timedelta
