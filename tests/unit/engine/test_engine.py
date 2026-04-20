"""Unit tests for TradeEngine — pure decision-function contract.

Uses deterministic fake strategies and risk gates. No exchange, no
network. These tests are the contract every real strategy + risk
manager must honor when plugged into the engine.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from engine import Decision, DecisionAction, EngineContext, TradeEngine
from strategies.base import BaseStrategy, Signal, SignalType

# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeStrategy(BaseStrategy):
    """Strategy that returns whatever Signal we hand it."""

    def __init__(self, signal: Signal):
        super().__init__("fake")
        self._signal = signal

    def analyze(self, df, current_position=None):  # noqa: ARG002
        return self._signal


@dataclass
class FakeRisk:
    can_trade_flag: bool = True
    can_open_flag: bool = True
    exit_reason: str | None = None

    def can_trade(self) -> bool:
        return self.can_trade_flag

    def can_open_position(self, current_positions: int) -> bool:  # noqa: ARG002
        return self.can_open_flag

    def check_position_exit(  # noqa: ARG002
        self, entry_price: float, current_price: float, is_long: bool
    ) -> str | None:
        return self.exit_reason


def _df_with_one_bar() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5], "volume": [10.0]}
    )


def _ctx(**kwargs) -> EngineContext:
    defaults = dict(
        symbol="BTC",
        current_price=100.0,
        candles_df=_df_with_one_bar(),
        current_position=None,
        entry_price=None,
        open_position_count=0,
    )
    defaults.update(kwargs)
    return EngineContext(**defaults)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestTradeEngineNoPosition:
    def test_hold_signal_produces_hold_decision(self) -> None:
        engine = TradeEngine(FakeStrategy(Signal(SignalType.HOLD, 0.0, "wait")), FakeRisk())
        decision = engine.decide(_ctx())

        assert decision.action is DecisionAction.HOLD
        assert decision.reason == "wait"
        assert decision.rejection is None
        assert not decision.is_actionable

    def test_long_signal_produces_open_long_when_risk_permits(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.LONG, 0.8, "breakout")), FakeRisk()
        )
        decision = engine.decide(_ctx())

        assert decision.action is DecisionAction.OPEN_LONG
        assert decision.reason == "breakout"
        assert decision.strength == 0.8
        assert decision.is_actionable

    def test_short_signal_produces_open_short_when_risk_permits(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.SHORT, 0.6, "breakdown")), FakeRisk()
        )
        decision = engine.decide(_ctx())

        assert decision.action is DecisionAction.OPEN_SHORT
        assert decision.reason == "breakdown"

    def test_daily_loss_limit_blocks_opens(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.LONG, 1.0, "strong")),
            FakeRisk(can_trade_flag=False),
        )
        decision = engine.decide(_ctx())

        assert decision.action is DecisionAction.HOLD
        assert decision.rejection is not None
        assert "daily loss" in decision.rejection.lower()

    def test_max_positions_limit_blocks_opens(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.LONG, 1.0, "strong")),
            FakeRisk(can_open_flag=False),
        )
        decision = engine.decide(_ctx(open_position_count=3))

        assert decision.action is DecisionAction.HOLD
        assert decision.rejection is not None
        assert "max" in decision.rejection.lower()

    def test_empty_candles_yields_hold(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.LONG, 1.0, "should_not_fire")), FakeRisk()
        )
        decision = engine.decide(_ctx(candles_df=pd.DataFrame()))

        assert decision.action is DecisionAction.HOLD
        assert "no market data" in decision.reason.lower()


class TestTradeEngineWithPosition:
    def test_stop_loss_triggers_close_long(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.HOLD)),
            FakeRisk(exit_reason="stop_loss"),
        )
        decision = engine.decide(
            _ctx(current_position="LONG", entry_price=105.0, current_price=100.0)
        )

        assert decision.action is DecisionAction.CLOSE_LONG
        assert decision.reason == "stop_loss"

    def test_take_profit_triggers_close_short(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.HOLD)),
            FakeRisk(exit_reason="take_profit"),
        )
        decision = engine.decide(
            _ctx(current_position="SHORT", entry_price=105.0, current_price=100.0)
        )

        assert decision.action is DecisionAction.CLOSE_SHORT
        assert decision.reason == "take_profit"

    def test_risk_exit_takes_priority_over_strategy_signal(self) -> None:
        # Strategy says LONG, but risk says close the existing LONG first.
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.LONG, 1.0, "pyramid")),
            FakeRisk(exit_reason="stop_loss"),
        )
        decision = engine.decide(
            _ctx(current_position="LONG", entry_price=105.0, current_price=100.0)
        )

        assert decision.action is DecisionAction.CLOSE_LONG
        assert decision.reason == "stop_loss"

    def test_strategy_close_long_closes_long_position(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.CLOSE_LONG, 1.0, "exit signal")),
            FakeRisk(),
        )
        decision = engine.decide(
            _ctx(current_position="LONG", entry_price=100.0, current_price=102.0)
        )

        assert decision.action is DecisionAction.CLOSE_LONG
        assert decision.reason == "exit signal"

    def test_strategy_close_long_is_ignored_when_not_in_long(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.CLOSE_LONG, 1.0, "exit signal")), FakeRisk()
        )
        decision = engine.decide(_ctx(current_position=None))

        assert decision.action is DecisionAction.HOLD
        assert decision.rejection is not None
        assert "CLOSE_LONG" in decision.rejection

    def test_strategy_close_short_closes_short_position(self) -> None:
        engine = TradeEngine(
            FakeStrategy(Signal(SignalType.CLOSE_SHORT, 1.0, "exit signal")),
            FakeRisk(),
        )
        decision = engine.decide(
            _ctx(current_position="SHORT", entry_price=100.0, current_price=98.0)
        )

        assert decision.action is DecisionAction.CLOSE_SHORT

    def test_hold_signal_holds_when_position_is_healthy(self) -> None:
        engine = TradeEngine(FakeStrategy(Signal(SignalType.HOLD, 0.0, "riding")), FakeRisk())
        decision = engine.decide(
            _ctx(current_position="LONG", entry_price=100.0, current_price=101.0)
        )

        assert decision.action is DecisionAction.HOLD


class TestDecision:
    @pytest.mark.parametrize(
        "action,expected",
        [
            (DecisionAction.OPEN_LONG, True),
            (DecisionAction.OPEN_SHORT, True),
            (DecisionAction.CLOSE_LONG, True),
            (DecisionAction.CLOSE_SHORT, True),
            (DecisionAction.HOLD, False),
        ],
    )
    def test_is_actionable_flag(self, action, expected) -> None:
        assert Decision(action=action).is_actionable is expected
