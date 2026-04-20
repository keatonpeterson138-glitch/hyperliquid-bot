"""Tests for OrderService + OrderRepository."""
from __future__ import annotations

from typing import Any

import pytest

from backend.db.app_db import AppDB
from backend.services.audit import AuditService
from backend.services.markup_store import MarkupStore
from backend.services.order_repository import OrderRepository
from backend.services.order_service import (
    ModifyOrderRequest,
    OrderGatewayError,
    OrderService,
    PlaceOrderRequest,
)


class FakeGateway:
    def __init__(self, *, fill_price: float | None = 100.0, raise_on_entry: bool = False) -> None:
        self.fill_price = fill_price
        self.raise_on_entry = raise_on_entry
        self.entry_calls: list[dict[str, Any]] = []
        self.trigger_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[dict[str, Any]] = []
        self.modify_calls: list[dict[str, Any]] = []
        self._next_id = 0

    def _next(self, kind: str) -> str:
        self._next_id += 1
        return f"xo_{kind}_{self._next_id}"

    def place_entry(self, **kw: Any) -> dict[str, Any]:
        if self.raise_on_entry:
            raise RuntimeError("exchange rejected")
        self.entry_calls.append(kw)
        return {"exchange_order_id": self._next("entry"), "fill_price": self.fill_price}

    def place_trigger(self, **kw: Any) -> dict[str, Any]:
        self.trigger_calls.append(kw)
        return {"exchange_order_id": self._next(kw["leg_type"])}

    def cancel(self, **kw: Any) -> dict[str, Any]:
        self.cancel_calls.append(kw)
        return {"ok": True}

    def modify_trigger(self, **kw: Any) -> dict[str, Any]:
        self.modify_calls.append(kw)
        return {"ok": True}


@pytest.fixture
def svc() -> tuple[OrderService, FakeGateway, OrderRepository, MarkupStore]:
    db = AppDB(":memory:")
    repo = OrderRepository(db)
    gw = FakeGateway()
    markup_store = MarkupStore(db)
    audit = AuditService(db)
    s = OrderService(repo, gw, audit=audit, markup_store=markup_store)
    yield s, gw, repo, markup_store
    db.close()


def test_place_market_long_with_brackets(svc) -> None:
    s, gw, repo, _ = svc
    order = s.place(PlaceOrderRequest(
        symbol="BTC", side="long", size_usd=100.0,
        entry_type="market", sl_price=95.0, tp_price=110.0, leverage=5,
    ))
    assert order.status == "working"
    assert order.fill_price == 100.0
    assert len(order.legs) == 3
    assert {leg.leg_type for leg in order.legs} == {"entry", "sl", "tp"}
    assert len(gw.entry_calls) == 1
    assert len(gw.trigger_calls) == 2


def test_place_rejects_invalid_long_bracket(svc) -> None:
    s, _, _, _ = svc
    # long SL must be below entry; 110 > 100 is invalid
    with pytest.raises(ValueError):
        s.place(PlaceOrderRequest(
            symbol="BTC", side="long", size_usd=100.0,
            entry_type="limit", entry_price=100.0, sl_price=110.0,
        ))


def test_place_gateway_failure_marks_rejected(svc) -> None:
    s, gw, repo, _ = svc
    gw.raise_on_entry = True
    with pytest.raises(OrderGatewayError):
        s.place(PlaceOrderRequest(symbol="BTC", side="long", size_usd=100.0))
    orders = repo.list()
    assert len(orders) == 1
    assert orders[0].status == "rejected"
    assert "exchange rejected" in (orders[0].reject_reason or "")


def test_modify_updates_triggers(svc) -> None:
    s, gw, _, _ = svc
    order = s.place(PlaceOrderRequest(
        symbol="BTC", side="long", size_usd=100.0,
        sl_price=95.0, tp_price=110.0,
    ))
    updated = s.modify(order.id, ModifyOrderRequest(sl_price=97.0))
    assert updated.sl_price == 97.0
    assert len(gw.modify_calls) == 1
    assert gw.modify_calls[0]["trigger_price"] == 97.0


def test_cancel_cancels_working_legs(svc) -> None:
    s, gw, _, _ = svc
    order = s.place(PlaceOrderRequest(
        symbol="BTC", side="long", size_usd=100.0,
        sl_price=95.0, tp_price=110.0,
    ))
    cancelled = s.cancel(order.id)
    assert cancelled.status == "cancelled"
    # entry + sl + tp = 3 working legs to cancel
    assert len(gw.cancel_calls) == 3


def test_cancel_idempotent(svc) -> None:
    s, _, _, _ = svc
    order = s.place(PlaceOrderRequest(symbol="BTC", side="long", size_usd=100.0))
    s.cancel(order.id)
    again = s.cancel(order.id)
    assert again.status == "cancelled"


def test_fill_writes_fill_marker(svc) -> None:
    s, _, _, markup_store = svc
    order = s.place(PlaceOrderRequest(
        symbol="BTC", side="long", size_usd=100.0, sl_price=95.0, tp_price=110.0,
    ))
    fills = markup_store.list(symbol="BTC")
    fill_markers = [m for m in fills if m.tool_id == "fill_marker"]
    assert len(fill_markers) == 1
    assert fill_markers[0].payload["price"] == 100.0
    assert fill_markers[0].payload["side"] == "buy"
    assert fill_markers[0].payload["order_id"] == order.id


def test_no_gateway_marks_pending_local(svc) -> None:
    s, _, repo, _ = svc
    s.gateway = None  # simulate dev mode
    order = s.place(PlaceOrderRequest(symbol="BTC", side="long", size_usd=100.0))
    assert order.status == "pending"
    assert len(order.legs) == 0
    assert len(repo.list()) == 1


def test_list_filters(svc) -> None:
    s, _, repo, _ = svc
    s.place(PlaceOrderRequest(symbol="BTC", side="long", size_usd=100.0))
    s.place(PlaceOrderRequest(symbol="ETH", side="short", size_usd=50.0))
    assert len(repo.list()) == 2
    assert len(repo.list(symbol="BTC")) == 1
    assert len(repo.list(status="working")) == 2
