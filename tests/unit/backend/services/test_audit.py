"""Tests for AuditService."""
from __future__ import annotations

import sqlite3

import pytest

from backend.db.app_db import AppDB
from backend.services.audit import AuditService


@pytest.fixture
def svc() -> AuditService:
    db = AppDB(":memory:")
    yield AuditService(db)
    db.close()


def test_log_returns_id(svc) -> None:
    i = svc.log("order_placed", source="strategy", symbol="BTC", size_usd=100.0)
    assert i > 0


def test_query_returns_most_recent_first(svc) -> None:
    svc.log("slot_started", source="user", slot_id="s1")
    svc.log("decision_emitted", source="strategy", slot_id="s1", symbol="BTC")
    events = svc.query()
    assert len(events) == 2
    assert events[0].event_type == "decision_emitted"
    assert events[1].event_type == "slot_started"


def test_filter_by_event_type(svc) -> None:
    svc.log("order_placed", source="strategy", symbol="BTC")
    svc.log("order_cancelled", source="strategy", symbol="BTC")
    events = svc.query(event_types=["order_placed"])
    assert len(events) == 1
    assert events[0].event_type == "order_placed"


def test_filter_by_symbol(svc) -> None:
    svc.log("order_placed", source="strategy", symbol="BTC")
    svc.log("order_placed", source="strategy", symbol="ETH")
    events = svc.query(symbol="ETH")
    assert len(events) == 1
    assert events[0].symbol == "ETH"


def test_filter_by_slot_id(svc) -> None:
    svc.log("slot_started", source="user", slot_id="s1")
    svc.log("slot_started", source="user", slot_id="s2")
    events = svc.query(slot_id="s1")
    assert len(events) == 1


def test_exchange_response_round_trips(svc) -> None:
    svc.log(
        "order_filled",
        source="exchange_ws",
        exchange_response={"order_id": "abc123", "filled_at": 102.5},
    )
    events = svc.query()
    assert events[0].exchange_response == {"order_id": "abc123", "filled_at": 102.5}


def test_append_only_trigger_enforced(svc) -> None:
    svc.log("order_placed", source="strategy")
    # Direct SQL bypass attempt — trigger must still block.
    with pytest.raises(sqlite3.IntegrityError):
        svc.db.execute("UPDATE audit_log SET event_type = 'x' WHERE id = 1")


def test_count_returns_total(svc) -> None:
    for i in range(5):
        svc.log("decision_emitted", source="strategy", slot_id=f"s{i}")
    assert svc.count() == 5
