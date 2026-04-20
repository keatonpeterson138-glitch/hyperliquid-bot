"""Tests for TradeEngineService."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.db.app_db import AppDB
from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.kill_switch import KillSwitchService
from backend.services.order_executor import OrderExecutor
from backend.services.slot_repository import SlotRepository
from backend.services.slot_runner import SlotRunner
from backend.services.trade_engine_service import TradeEngineService
from engine import DecisionAction
from strategies.base import BaseStrategy, Signal, SignalType


class _Strategy(BaseStrategy):
    def __init__(self, signal: Signal):
        super().__init__("test")
        self._signal = signal

    def analyze(self, df, current_position=None):  # noqa: ARG002
        return self._signal


@dataclass
class FakeExchange:
    price: float = 100.0
    cancel_calls: int = 0
    place_calls: list = field(default_factory=list)
    close_calls: list = field(default_factory=list)

    def get_market_price(self, s):  # noqa: ARG002
        return self.price

    def place_market_order(self, symbol, is_buy, size_usd, leverage):
        self.place_calls.append((symbol, is_buy, size_usd, leverage))
        return {"order_id": "x", "fill_price": self.price}

    def close_position(self, symbol, dex=""):
        self.close_calls.append((symbol, dex))
        return {"status": "closed"}

    def cancel_all(self):
        self.cancel_calls += 1
        return []

    def get_all_positions(self):
        return []


def _candle_query():
    df = pd.DataFrame(
        {
            "open": [100.0] * 50,
            "high": [101.0] * 50,
            "low": [99.0] * 50,
            "close": [100.0] * 50,
            "volume": [1000.0] * 50,
        },
        index=pd.to_datetime(
            [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(50)],
            utc=True,
        ),
    )
    return lambda *_a, **_kw: df


@pytest.fixture
def svc():
    db = AppDB(":memory:")
    repo = SlotRepository(db)
    audit = AuditService(db)
    exchange = FakeExchange()
    runner = SlotRunner(
        repo=repo, audit=audit, exchange=exchange,
        candle_query=_candle_query(),
        strategy_factory=lambda *_a, **_kw: _Strategy(Signal(SignalType.LONG, 1.0, "go")),
        executor=OrderExecutor(),
    )
    kill_switch = KillSwitchService(exchange, db, audit)
    yield TradeEngineService(repo, runner, kill_switch=kill_switch), repo, exchange, kill_switch
    db.close()


def _slot(**overrides) -> Slot:
    defaults = dict(
        id="",
        kind="perp",
        symbol="BTC",
        strategy="ema_crossover",
        size_usd=100.0,
        interval="1h",
        strategy_params={},
        leverage=3,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        enabled=False,
    )
    defaults.update(overrides)
    return Slot(**defaults)


def test_start_slot_enables(svc) -> None:
    s, repo, _, _ = svc
    slot = repo.create(_slot())
    s.start_slot(slot.id)
    assert repo.get(slot.id).enabled is True


def test_stop_all_disables_every_enabled_slot(svc) -> None:
    s, repo, _, _ = svc
    repo.create(_slot(enabled=True))
    repo.create(_slot(enabled=True))
    repo.create(_slot(enabled=False))
    n = s.stop_all()
    assert n == 2
    assert all(not slot.enabled for slot in repo.list_all())


def test_tick_executes_when_enabled(svc) -> None:
    s, repo, exchange, _ = svc
    slot = repo.create(_slot(enabled=True))
    decision = s.tick(slot.id)
    assert decision.action is DecisionAction.OPEN_LONG
    assert exchange.place_calls != []


def test_tick_holds_when_kill_switch_active(svc) -> None:
    s, repo, exchange, kill = svc
    slot = repo.create(_slot(enabled=True))
    kill.activate(confirmation="KILL")
    # Slot got disabled by activate(); also kill_switch is_active=True.
    decision = s.tick(slot.id)
    assert decision.action is DecisionAction.HOLD


def test_tick_unknown_slot_holds(svc) -> None:
    s, _, _, _ = svc
    decision = s.tick("nonexistent")
    assert decision.action is DecisionAction.HOLD


def test_tick_all_enabled_runs_each(svc) -> None:
    s, repo, exchange, _ = svc
    repo.create(_slot(enabled=True, symbol="BTC"))
    repo.create(_slot(enabled=True, symbol="ETH"))
    repo.create(_slot(enabled=False, symbol="SOL"))
    decisions = s.tick_all_enabled()
    assert len(decisions) == 2
    assert {sym for sym, *_ in exchange.place_calls} == {"BTC", "ETH"}


def test_event_callbacks_fire(svc) -> None:
    s, repo, _, _ = svc
    received = []
    s.on_event = received.append
    slot = repo.create(_slot())
    s.start_slot(slot.id)
    s.stop_slot(slot.id)
    types = {ev["type"] for ev in received}
    assert types == {"slot_started", "slot_stopped"}
