"""TradeEngine — headless, exchange-agnostic trading decision engine.

The engine is a pure function of its inputs: given a context (position,
price, candles) it emits a ``Decision`` describing what the caller should
do. It never touches the exchange. The caller — `bot.py`, `dashboard.py`,
or the future FastAPI backend — is responsible for order placement,
SL/TP management, and state persistence.

This separation lets the same decision logic run in live trading,
backtest, and shadow mode, and makes the engine trivially unit-testable.

Architectural note: this module is the seed of Phase 0-A of the overhaul
plan (`internal_docs/OVERHAUL_PLAN.md`). The long-term home for the
engine is `backend/services/trade_engine.py`, but it lives at the repo
root now so both `bot.py` and `dashboard.py` can import it during the
migration. The module moves once `backend/` exists (Phase 2).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import pandas as pd

from strategies.base import BaseStrategy, SignalType


class DecisionAction(Enum):
    """What the engine is recommending the caller do this iteration."""

    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"


@dataclass(frozen=True)
class EngineContext:
    """Snapshot of everything the engine needs to decide one iteration."""

    symbol: str
    current_price: float
    candles_df: pd.DataFrame
    current_position: str | None = None  # 'LONG' | 'SHORT' | None
    entry_price: float | None = None
    open_position_count: int = 0


@dataclass(frozen=True)
class Decision:
    """Engine output. Caller executes `action`."""

    action: DecisionAction
    reason: str = ""
    strength: float = 0.0
    rejection: str | None = None  # set when a signal was gated by risk

    @property
    def is_actionable(self) -> bool:
        """True when the caller should place or close an order."""
        return self.action is not DecisionAction.HOLD


class RiskGate(Protocol):
    """Subset of RiskManager the engine depends on.

    Accepts the existing `core.risk_manager.RiskManager` unchanged and
    also allows a fake for tests without importing the real module.
    """

    def can_trade(self) -> bool: ...
    def can_open_position(self, current_positions: int) -> bool: ...
    def check_position_exit(
        self, entry_price: float, current_price: float, is_long: bool
    ) -> str | None: ...


@dataclass
class TradeEngine:
    """Decide the next trading action given current state.

    The engine is stateless — no iteration state is retained between
    `decide()` calls. All inputs are passed in via `EngineContext`.
    """

    strategy: BaseStrategy
    risk: RiskGate

    def decide(self, ctx: EngineContext) -> Decision:
        # 1. If we already have a position, risk-manager exits take priority.
        if ctx.current_position and ctx.entry_price is not None:
            is_long = ctx.current_position == "LONG"
            exit_reason = self.risk.check_position_exit(
                ctx.entry_price, ctx.current_price, is_long
            )
            if exit_reason:
                return Decision(
                    action=DecisionAction.CLOSE_LONG if is_long else DecisionAction.CLOSE_SHORT,
                    reason=exit_reason,
                )

        # 2. No candles → nothing to decide on.
        if ctx.candles_df is None or ctx.candles_df.empty:
            return Decision(DecisionAction.HOLD, reason="No market data")

        # 3. Run the strategy.
        signal = self.strategy.analyze(ctx.candles_df, current_position=ctx.current_position)

        if signal.signal_type is SignalType.HOLD:
            return Decision(
                DecisionAction.HOLD,
                reason=signal.reason,
                strength=signal.strength,
            )

        # 4. Close signals from the strategy — only valid if we have a position.
        if signal.signal_type is SignalType.CLOSE_LONG:
            if ctx.current_position == "LONG":
                return Decision(
                    DecisionAction.CLOSE_LONG,
                    reason=signal.reason,
                    strength=signal.strength,
                )
            return Decision(
                DecisionAction.HOLD,
                reason=signal.reason,
                strength=signal.strength,
                rejection="CLOSE_LONG signal but no LONG position",
            )

        if signal.signal_type is SignalType.CLOSE_SHORT:
            if ctx.current_position == "SHORT":
                return Decision(
                    DecisionAction.CLOSE_SHORT,
                    reason=signal.reason,
                    strength=signal.strength,
                )
            return Decision(
                DecisionAction.HOLD,
                reason=signal.reason,
                strength=signal.strength,
                rejection="CLOSE_SHORT signal but no SHORT position",
            )

        # 5. Open signals — gate through risk.
        if signal.signal_type in (SignalType.LONG, SignalType.SHORT):
            if not self.risk.can_trade():
                return Decision(
                    DecisionAction.HOLD,
                    reason=signal.reason,
                    strength=signal.strength,
                    rejection="Trading paused (daily loss limit)",
                )
            if not self.risk.can_open_position(ctx.open_position_count):
                return Decision(
                    DecisionAction.HOLD,
                    reason=signal.reason,
                    strength=signal.strength,
                    rejection="Max open positions reached",
                )

            action = (
                DecisionAction.OPEN_LONG
                if signal.signal_type is SignalType.LONG
                else DecisionAction.OPEN_SHORT
            )
            return Decision(action=action, reason=signal.reason, strength=signal.strength)

        # 6. Unknown signal — be defensive.
        return Decision(
            DecisionAction.HOLD,
            reason=f"Unknown signal type: {signal.signal_type}",
        )
