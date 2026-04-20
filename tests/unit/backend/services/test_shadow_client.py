"""Tests for ShadowRunner."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.db.app_db import AppDB
from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.shadow_client import ShadowRunner
from engine import Decision, DecisionAction


@dataclass
class FakeTestnet:
    place_calls: list = field(default_factory=list)
    close_calls: list = field(default_factory=list)

    def get_market_price(self, s):  # noqa: ARG002
        return 100.0

    def place_market_order(self, symbol, is_buy, size_usd, leverage):
        self.place_calls.append((symbol, is_buy, size_usd, leverage))
        return {"order_id": "shadow_o1", "fill_price": 100.0}

    def close_position(self, symbol, dex=""):
        self.close_calls.append((symbol, dex))
        return {"status": "closed"}


def _slot(**overrides) -> Slot:
    defaults = dict(
        id="s1",
        kind="perp",
        symbol="BTC",
        strategy="ema_crossover",
        size_usd=100.0,
        interval="1h",
        leverage=2,
    )
    defaults.update(overrides)
    return Slot(**defaults)


@pytest.fixture
def harness():
    db = AppDB(":memory:")
    yield AuditService(db)
    db.close()


def test_matching_decisions_no_divergence(harness) -> None:
    audit = harness
    testnet = FakeTestnet()
    runner = ShadowRunner(testnet, audit)
    slot = _slot()
    same = Decision(DecisionAction.HOLD, "no signal")
    runner.record(slot, same, same)
    assert runner.state(slot.id).divergence_count == 0


def test_divergence_audited_and_callbacks_fire(harness) -> None:
    audit = harness
    testnet = FakeTestnet()
    received = []
    runner = ShadowRunner(testnet, audit, on_divergence=[received.append])
    slot = _slot()
    runner.record(
        slot,
        Decision(DecisionAction.OPEN_LONG, "bullish"),
        Decision(DecisionAction.HOLD, "wait"),
    )
    state = runner.state(slot.id)
    assert state.divergence_count == 1
    assert state.last_divergence is not None
    assert len(received) == 1
    events = audit.query()
    assert any(e.event_type == "shadow_divergence" for e in events)


def test_shadow_decision_executes_on_testnet(harness) -> None:
    audit = harness
    testnet = FakeTestnet()
    runner = ShadowRunner(testnet, audit)
    slot = _slot()
    # Both agree LONG; shadow still fires testnet order.
    runner.record(
        slot,
        Decision(DecisionAction.OPEN_LONG, "go"),
        Decision(DecisionAction.OPEN_LONG, "go"),
    )
    assert testnet.place_calls == [(slot.symbol, True, slot.size_usd, slot.leverage)]
    assert runner.state(slot.id).testnet_position == "LONG"


def test_close_clears_shadow_position(harness) -> None:
    audit = harness
    testnet = FakeTestnet()
    runner = ShadowRunner(testnet, audit)
    slot = _slot()
    runner.record(
        slot,
        Decision(DecisionAction.OPEN_LONG, "go"),
        Decision(DecisionAction.OPEN_LONG, "go"),
    )
    runner.record(
        slot,
        Decision(DecisionAction.CLOSE_LONG, "exit"),
        Decision(DecisionAction.CLOSE_LONG, "exit"),
    )
    assert runner.state(slot.id).testnet_position is None
    assert testnet.close_calls == [(slot.symbol, "")]


def test_callback_exception_does_not_raise(harness) -> None:
    audit = harness
    testnet = FakeTestnet()

    def bad_callback(_event):
        raise RuntimeError("boom")

    runner = ShadowRunner(testnet, audit, on_divergence=[bad_callback])
    runner.record(
        _slot(),
        Decision(DecisionAction.OPEN_LONG, "go"),
        Decision(DecisionAction.HOLD, "wait"),
    )
    # No raise.
