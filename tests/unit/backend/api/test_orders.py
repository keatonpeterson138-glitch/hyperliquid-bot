"""API tests for /orders — bracket order CRUD + from-markup promotion."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api import orders as orders_api
from backend.db.app_db import AppDB
from backend.main import create_app
from backend.services.markup_store import MarkupStore
from backend.services.order_repository import OrderRepository
from backend.services.order_service import OrderService


class _FakeGateway:
    def __init__(self) -> None:
        self._n = 0
        self.cancel_count = 0
        self.modify_count = 0

    def _next(self, p: str) -> str:
        self._n += 1
        return f"xo_{p}_{self._n}"

    def place_entry(self, **_: Any) -> dict:
        return {"exchange_order_id": self._next("entry"), "fill_price": 100.0}

    def place_trigger(self, *, leg_type: str, **_: Any) -> dict:
        return {"exchange_order_id": self._next(leg_type)}

    def cancel(self, **_: Any) -> dict:
        self.cancel_count += 1
        return {"ok": True}

    def modify_trigger(self, **_: Any) -> dict:
        self.modify_count += 1
        return {"ok": True}


@pytest.fixture
def client() -> tuple[TestClient, OrderService, MarkupStore]:
    db = AppDB(":memory:")
    repo = OrderRepository(db)
    ms = MarkupStore(db)
    svc = OrderService(repo, _FakeGateway(), markup_store=ms)

    app = create_app()
    app.dependency_overrides[orders_api.get_order_service] = lambda: svc
    app.dependency_overrides[orders_api.get_markup_store_for_orders] = lambda: ms
    yield TestClient(app), svc, ms
    db.close()


def test_post_order_returns_working_bracket(client) -> None:
    c, _, _ = client
    resp = c.post(
        "/orders",
        json={
            "symbol": "BTC",
            "side": "long",
            "size_usd": 100.0,
            "entry_type": "market",
            "sl_price": 95.0,
            "tp_price": 110.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "working"
    assert body["fill_price"] == 100.0
    assert len(body["legs"]) == 3
    assert {leg["leg_type"] for leg in body["legs"]} == {"entry", "sl", "tp"}


def test_post_order_validates_bracket(client) -> None:
    c, _, _ = client
    resp = c.post(
        "/orders",
        json={
            "symbol": "BTC", "side": "long", "size_usd": 100.0,
            "entry_type": "limit", "entry_price": 100.0, "sl_price": 110.0,
        },
    )
    assert resp.status_code == 400
    assert "long SL" in resp.json()["detail"]


def test_patch_modifies_prices(client) -> None:
    c, _, _ = client
    created = c.post("/orders", json={
        "symbol": "BTC", "side": "long", "size_usd": 100.0,
        "sl_price": 95.0, "tp_price": 110.0,
    }).json()
    resp = c.patch(f"/orders/{created['id']}", json={"sl_price": 97.0})
    assert resp.status_code == 200
    assert resp.json()["sl_price"] == 97.0


def test_patch_unknown_is_404(client) -> None:
    c, _, _ = client
    resp = c.patch("/orders/ord_bogus", json={"sl_price": 97.0})
    assert resp.status_code == 404


def test_delete_cancels(client) -> None:
    c, _, _ = client
    created = c.post("/orders", json={
        "symbol": "BTC", "side": "long", "size_usd": 100.0,
        "sl_price": 95.0, "tp_price": 110.0,
    }).json()
    resp = c.delete(f"/orders/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_list_filters_by_symbol(client) -> None:
    c, _, _ = client
    c.post("/orders", json={"symbol": "BTC", "side": "long", "size_usd": 100.0})
    c.post("/orders", json={"symbol": "ETH", "side": "short", "size_usd": 50.0})
    resp = c.get("/orders", params={"symbol": "BTC"})
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) == 1
    assert orders[0]["symbol"] == "BTC"


def test_from_markup_promotes_long_position(client) -> None:
    c, _, ms = client
    m = ms.create(
        symbol="BTC",
        tool_id="long_position",
        payload={"entry": 100.0, "sl": 95.0, "tp": 110.0},
    )
    resp = c.post("/orders/from-markup", json={
        "markup_id": m.id, "size_usd": 100.0, "leverage": 5,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["markup_id"] == m.id
    assert body["source"] == "markup"
    assert body["side"] == "long"
    # Markup transitioned to pending + linked
    refreshed = ms.get(m.id)
    assert refreshed is not None
    assert refreshed.state == "pending"
    assert refreshed.order_id == body["id"]


def test_from_markup_rejects_non_position_tool(client) -> None:
    c, _, ms = client
    m = ms.create(symbol="BTC", tool_id="horizontal_line", payload={"price": 100})
    resp = c.post("/orders/from-markup", json={"markup_id": m.id, "size_usd": 50})
    assert resp.status_code == 400


def test_from_markup_unknown_id_404(client) -> None:
    c, _, _ = client
    resp = c.post("/orders/from-markup", json={"markup_id": "markup_bogus", "size_usd": 50})
    assert resp.status_code == 404


def test_without_override_returns_503() -> None:
    """Without overriding get_order_service, the stub raises 503."""
    app = create_app()
    c = TestClient(app)
    resp = c.get("/orders")
    assert resp.status_code == 503
