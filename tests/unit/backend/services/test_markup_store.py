"""Tests for MarkupStore."""
from __future__ import annotations

import pytest

from backend.db.app_db import AppDB
from backend.services.markup_store import MarkupStore


@pytest.fixture
def store() -> MarkupStore:
    db = AppDB(":memory:")
    yield MarkupStore(db)
    db.close()


def test_create_then_get(store) -> None:
    m = store.create(symbol="BTC", tool_id="horizontal_line", payload={"price": 50000})
    assert m.id.startswith("markup_")
    fetched = store.get(m.id)
    assert fetched.tool_id == "horizontal_line"
    assert fetched.payload == {"price": 50000}
    assert fetched.state == "draft"


def test_list_filters(store) -> None:
    store.create(symbol="BTC", interval="1h", tool_id="trendline", payload={})
    store.create(symbol="BTC", interval="4h", tool_id="trendline", payload={})
    store.create(symbol="ETH", interval="1h", tool_id="trendline", payload={})

    assert len(store.list()) == 3
    assert len(store.list(symbol="BTC")) == 2
    assert len(store.list(symbol="BTC", interval="1h")) == 1


def test_update_fields(store) -> None:
    m = store.create(symbol="BTC", tool_id="horizontal_line", payload={"price": 50000})
    updated = store.update(m.id, {"payload": {"price": 51000}, "state": "active"})
    assert updated.payload == {"price": 51000}
    assert updated.state == "active"


def test_delete(store) -> None:
    m = store.create(symbol="BTC", tool_id="horizontal_line", payload={"price": 50000})
    store.delete(m.id)
    assert store.get(m.id) is None


def test_locked_hidden_round_trip(store) -> None:
    m = store.create(symbol="BTC", tool_id="trendline", payload={})
    store.update(m.id, {"locked": True, "hidden": True})
    fetched = store.get(m.id)
    assert fetched.locked is True
    assert fetched.hidden is True
