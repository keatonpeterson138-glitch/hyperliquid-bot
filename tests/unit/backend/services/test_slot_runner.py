"""Tests for SlotRunner — fake exchange + deterministic strategy + AppDB."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from backend.db.app_db import AppDB
from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.order_executor import OrderExecutor
from backend.services.slot_repository import SlotRepository
from backend.services.slot_runner import SlotRiskAdapter, SlotRunner
from engine import DecisionAction
from strategies.base import BaseStrategy, Signal, SignalType


class _ScriptedStrategy(BaseStrategy):
    def __init__(self, signal: Signal):
        super().__init__("scripted")
        self._signal = signal

    def analyze(self, df, current_position=None):  # noqa: ARG002
        return self._signal


@dataclass
class FakeExchange:
    price: float = 100.0
    place_responses: list[dict[str, Any]] = field(default_factory=list)
    close_responses: list[dict[str, Any]] = field(default_factory=list)
    place_calls: list[tuple[str, bool, float, int]] = field(default_factory=list)
    close_calls: list[tuple[str, str]] = field(default_factory=list)
    raise_on_price: bool = False

    def get_market_price(self, symbol: str) -> float | None:
        if self.raise_on_price:
            raise RuntimeError("price feed down")
        return self.price

    def place_market_order(self, symbol, is_buy, size_usd, leverage):
        self.place_calls.append((symbol, is_buy, size_usd, leverage))
        if self.place_responses:
            return self.place_responses.pop(0)
        return {"order_id": "ord_1", "fill_price": self.price}

    def close_position(self, symbol, dex=""):
        self.close_calls.append((symbol, dex))
        if self.close_responses:
            return self.close_responses.pop(0)
        return {"status": "closed", "symbol": symbol}


def _candle_query(*, return_df: pd.DataFrame):
    def _q(symbol, interval, start, end):  # noqa: ARG001
        return return_df

    return _q


def _df_with_n_bars(n: int = 50) -> pd.DataFrame:
    ts = pd.to_datetime(
        [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)],
        utc=True,
    )
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
        },
        index=ts,
    )


@pytest.fixture
def harness():
    db = AppDB(":memory:")
    repo = SlotRepository(db)
    audit = AuditService(db)
    yield db, repo, audit
    db.close()


def _new_slot(**overrides) -> Slot:
    defaults = dict(
        id="slot_test",
        kind="perp",
        symbol="BTC",
        strategy="scripted",
        size_usd=100.0,
        interval="1h",
        strategy_params={},
        leverage=2,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        enabled=True,
    )
    defaults.update(overrides)
    return Slot(**defaults)


class TestSlotRunnerHappyPaths:
    def test_long_signal_places_market_buy(self, harness) -> None:
        db, repo, audit = harness
        slot = repo.create(_new_slot())
        ex = FakeExchange(price=100.0)
        runner = SlotRunner(
            repo=repo,
            audit=audit,
            exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.LONG, 1.0, "go long")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.OPEN_LONG
        assert ex.place_calls == [(slot.symbol, True, slot.size_usd, slot.leverage)]
        # Position state recorded.
        state = repo.get_state(slot.id)
        assert state.current_position == "LONG"
        assert state.entry_price == 100.0

    def test_short_signal_places_market_sell(self, harness) -> None:
        _, repo, audit = harness
        slot = repo.create(_new_slot())
        ex = FakeExchange()
        runner = SlotRunner(
            repo=repo,
            audit=audit,
            exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.SHORT, 1.0, "go short")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.OPEN_SHORT
        assert ex.place_calls[0][1] is False
        state = repo.get_state(slot.id)
        assert state.current_position == "SHORT"

    def test_close_long_when_in_long(self, harness) -> None:
        _, repo, audit = harness
        slot = repo.create(_new_slot())
        repo.upsert_state(slot.id, current_position="LONG", entry_price=100.0)
        ex = FakeExchange()
        runner = SlotRunner(
            repo=repo,
            audit=audit,
            exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.CLOSE_LONG, 1.0, "exit")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.CLOSE_LONG
        assert len(ex.close_calls) == 1
        state = repo.get_state(slot.id)
        assert state.current_position is None

    def test_stop_loss_triggers_close_when_in_long(self, harness) -> None:
        _, repo, audit = harness
        slot = repo.create(_new_slot(stop_loss_pct=2.0))
        repo.upsert_state(slot.id, current_position="LONG", entry_price=100.0)
        # Price dropped 3% — stop loss fires.
        ex = FakeExchange(price=97.0)
        runner = SlotRunner(
            repo=repo,
            audit=audit,
            exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(Signal(SignalType.HOLD)),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.CLOSE_LONG
        assert "stop_loss" in decision.reason


class TestSlotRunnerEdgeCases:
    def test_disabled_slot_holds(self, harness) -> None:
        _, repo, audit = harness
        slot = _new_slot(enabled=False)
        repo.create(slot)
        ex = FakeExchange()
        runner = SlotRunner(
            repo=repo, audit=audit, exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.LONG, 1.0, "go")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.HOLD
        assert ex.place_calls == []

    def test_price_fetch_failure_holds(self, harness) -> None:
        _, repo, audit = harness
        slot = repo.create(_new_slot())
        ex = FakeExchange(raise_on_price=True)
        runner = SlotRunner(
            repo=repo, audit=audit, exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.LONG, 1.0, "go")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.HOLD
        # Audit captured the rejection.
        events = audit.query()
        assert any("price fetch failed" in (e.reason or "") for e in events)

    def test_hold_signal_records_state_without_executing(self, harness) -> None:
        _, repo, audit = harness
        slot = repo.create(_new_slot())
        ex = FakeExchange()
        runner = SlotRunner(
            repo=repo, audit=audit, exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.HOLD, 0.0, "wait")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.HOLD
        assert ex.place_calls == []
        state = repo.get_state(slot.id)
        assert state.last_decision_action == "hold"

    def test_unknown_interval_holds(self, harness) -> None:
        _, repo, audit = harness
        slot = repo.create(_new_slot(interval="invalid"))
        ex = FakeExchange()
        runner = SlotRunner(
            repo=repo, audit=audit, exchange=ex,
            candle_query=_candle_query(return_df=_df_with_n_bars()),
            strategy_factory=lambda *_a, **_kw: _ScriptedStrategy(
                Signal(SignalType.LONG, 1.0, "go")
            ),
        )
        decision = runner.tick(slot)
        assert decision.action is DecisionAction.HOLD


class TestSlotRiskAdapter:
    def test_stop_loss_long(self) -> None:
        slot = _new_slot(stop_loss_pct=2.0)
        risk = SlotRiskAdapter(slot)
        assert risk.check_position_exit(100.0, 97.0, is_long=True) == "stop_loss"
        assert risk.check_position_exit(100.0, 99.0, is_long=True) is None

    def test_take_profit_short(self) -> None:
        slot = _new_slot(take_profit_pct=2.0)
        risk = SlotRiskAdapter(slot)
        # Short profits when price falls.
        assert risk.check_position_exit(100.0, 97.0, is_long=False) == "take_profit"

    def test_no_exit_when_no_threshold(self) -> None:
        slot = _new_slot(stop_loss_pct=None, take_profit_pct=None)
        risk = SlotRiskAdapter(slot)
        assert risk.check_position_exit(100.0, 50.0, is_long=True) is None


class TestOrderExecutor:
    def test_open_long_calls_place_market_buy(self) -> None:
        slot = _new_slot()
        ex = FakeExchange()
        from engine import Decision

        result = OrderExecutor().execute(
            Decision(DecisionAction.OPEN_LONG, "go"), slot, ex
        )
        assert result.success
        assert ex.place_calls[0] == (slot.symbol, True, slot.size_usd, slot.leverage)

    def test_close_long_calls_close_position_with_dex(self) -> None:
        slot = _new_slot(symbol="xyz:TSLA")
        ex = FakeExchange()
        from engine import Decision

        result = OrderExecutor().execute(
            Decision(DecisionAction.CLOSE_LONG, "exit"), slot, ex
        )
        assert result.success
        assert ex.close_calls[0] == ("xyz:TSLA", "xyz")

    def test_exception_yields_failed_result(self) -> None:
        class BrokenExchange:
            def get_market_price(self, s):  # noqa: ARG002
                return 100.0

            def place_market_order(self, *a, **kw):
                raise RuntimeError("rate limited")

            def close_position(self, *a, **kw):
                return {}

        from engine import Decision

        result = OrderExecutor().execute(
            Decision(DecisionAction.OPEN_LONG, "go"), _new_slot(), BrokenExchange()
        )
        assert not result.success
        assert "rate limited" in (result.error or "")
