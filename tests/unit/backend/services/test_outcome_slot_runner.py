"""Tests for OutcomeSlotRunner."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.db.app_db import AppDB
from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.outcome_slot_runner import OutcomeSlotRunner
from backend.services.slot_repository import SlotRepository
from engine import DecisionAction


@dataclass
class _Theory:
    fair_yes: float
    fair_no: float


@dataclass
class _AnalysisResult:
    underlying: str
    market_yes: float
    market_no: float
    theory: _Theory
    edge_yes: float
    edge_no: float


class _FakePricingModel:
    def __init__(self, edge: float | None) -> None:
        self.edge = edge

    def analyse(self, outcome_id: int, default_vol: float = 0.8, **_):
        if self.edge is None:
            return None
        return _AnalysisResult(
            underlying="BTC",
            market_yes=0.30,
            market_no=0.70,
            theory=_Theory(fair_yes=0.30 + self.edge, fair_no=0.70 - self.edge),
            edge_yes=self.edge,
            edge_no=-self.edge,
        )


@pytest.fixture
def rig():
    db = AppDB(":memory:")
    repo = SlotRepository(db)
    audit = AuditService(db)
    events: list[dict] = []
    runner = OutcomeSlotRunner(
        repo=repo, audit=audit,
        pricing_model=_FakePricingModel(edge=0.10),
        on_event=events.append,
    )
    yield runner, events, repo
    db.close()


def _outcome_slot(repo: SlotRepository, *, enabled: bool = True) -> Slot:
    return repo.create(Slot(
        id="",
        kind="outcome",
        symbol="outcome:4557",
        strategy="outcome_arb",
        size_usd=50.0,
        interval=None,
        strategy_params={"edge_threshold": 0.03},
        leverage=None,
        stop_loss_pct=None,
        take_profit_pct=None,
        enabled=enabled,
    ))


def test_positive_edge_opens_long(rig) -> None:
    runner, events, repo = rig
    slot = _outcome_slot(repo)
    d = runner.tick(slot)
    assert d.action is DecisionAction.OPEN_LONG
    # emitted both outcome_edge and decision
    kinds = [e["type"] for e in events]
    assert "outcome_edge" in kinds
    assert "decision" in kinds


def test_negative_edge_opens_short(rig) -> None:
    runner, _, repo = rig
    slot = _outcome_slot(repo)
    runner.pricing_model = _FakePricingModel(edge=-0.08)
    d = runner.tick(slot)
    assert d.action is DecisionAction.OPEN_SHORT


def test_edge_below_threshold_holds(rig) -> None:
    runner, _, repo = rig
    slot = _outcome_slot(repo)
    runner.pricing_model = _FakePricingModel(edge=0.01)
    d = runner.tick(slot)
    assert d.action is DecisionAction.HOLD
    assert "below threshold" in (d.reason or "")


def test_missing_pricing_holds(rig) -> None:
    runner, _, repo = rig
    slot = _outcome_slot(repo)
    runner.pricing_model = _FakePricingModel(edge=None)
    d = runner.tick(slot)
    assert d.action is DecisionAction.HOLD


def test_disabled_slot_holds(rig) -> None:
    runner, _, repo = rig
    slot = _outcome_slot(repo, enabled=False)
    d = runner.tick(slot)
    assert d.action is DecisionAction.HOLD
    assert "disabled" in (d.reason or "")


def test_non_outcome_slot_holds(rig) -> None:
    runner, _, repo = rig
    perp = repo.create(Slot(
        id="",
        kind="perp",
        symbol="BTC",
        strategy="ema_crossover",
        size_usd=100,
        interval="1h",
    ))
    d = runner.tick(perp)
    assert d.action is DecisionAction.HOLD
    assert "not an outcome slot" in (d.reason or "")


def test_bad_outcome_symbol_holds(rig) -> None:
    runner, _, repo = rig
    bad = repo.create(Slot(
        id="",
        kind="outcome",
        symbol="outcome:not_a_number",
        strategy="outcome_arb",
        size_usd=50,
        enabled=True,
    ))
    d = runner.tick(bad)
    assert d.action is DecisionAction.HOLD
    assert "bad outcome symbol" in (d.reason or "")


def test_edge_flip_closes_existing(rig) -> None:
    runner, _, repo = rig
    slot = _outcome_slot(repo)
    # Seed existing LONG position
    repo.upsert_state(slot.id, current_position="LONG", entry_price=0.30)
    runner.pricing_model = _FakePricingModel(edge=-0.08)  # now negative
    d = runner.tick(slot)
    assert d.action is DecisionAction.CLOSE_LONG
