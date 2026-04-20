"""/orders — bracket order placement + modify + cancel.

Also exposes ``POST /orders/from-markup`` which promotes a ``long_position``
or ``short_position`` chart markup into a live bracket and transitions
the markup's state from ``draft`` → ``pending`` → ``working``.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.models.order import (
    OrderCreate,
    OrderFromMarkup,
    OrderLegOut,
    OrderModify,
    OrderOut,
)
from backend.services.markup_store import MarkupStore
from backend.services.order_repository import Order
from backend.services.order_service import (
    ModifyOrderRequest,
    OrderGatewayError,
    OrderService,
    PlaceOrderRequest,
)

router = APIRouter(tags=["orders"])


def get_order_service() -> OrderService:
    raise HTTPException(status_code=503, detail="OrderService not configured")


def get_markup_store_for_orders() -> MarkupStore:
    """Separate hook so /orders tests can override independently of /markups."""
    raise HTTPException(status_code=503, detail="MarkupStore not configured")


OrderSvcDep = Annotated[OrderService, Depends(get_order_service)]
MarkupStoreDep = Annotated[MarkupStore, Depends(get_markup_store_for_orders)]


def _to_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        symbol=order.symbol,
        side=order.side,  # type: ignore[arg-type]
        size_usd=order.size_usd,
        entry_type=order.entry_type,  # type: ignore[arg-type]
        entry_price=order.entry_price,
        sl_price=order.sl_price,
        tp_price=order.tp_price,
        leverage=order.leverage,
        status=order.status,
        slot_id=order.slot_id,
        markup_id=order.markup_id,
        exchange_order_id=order.exchange_order_id,
        fill_price=order.fill_price,
        source=order.source,
        reject_reason=order.reject_reason,
        legs=[
            OrderLegOut(
                id=leg.id,
                leg_type=leg.leg_type,  # type: ignore[arg-type]
                exchange_order_id=leg.exchange_order_id,
                price=leg.price,
                status=leg.status,
            )
            for leg in order.legs
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    svc: OrderSvcDep,
    slot_id: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    markup_id: str | None = None,
) -> list[OrderOut]:
    orders = svc.repo.list(
        slot_id=slot_id, symbol=symbol, status=status, markup_id=markup_id
    )
    return [_to_out(o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: str, svc: OrderSvcDep) -> OrderOut:
    order = svc.repo.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_id}")
    return _to_out(order)


@router.post("/orders", response_model=OrderOut)
def create_order(req: OrderCreate, svc: OrderSvcDep) -> OrderOut:
    try:
        order = svc.place(
            PlaceOrderRequest(
                symbol=req.symbol,
                side=req.side,
                size_usd=req.size_usd,
                entry_type=req.entry_type,
                entry_price=req.entry_price,
                sl_price=req.sl_price,
                tp_price=req.tp_price,
                leverage=req.leverage,
                slot_id=req.slot_id,
                markup_id=req.markup_id,
                source=req.source,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OrderGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_out(order)


@router.patch("/orders/{order_id}", response_model=OrderOut)
def modify_order(order_id: str, req: OrderModify, svc: OrderSvcDep) -> OrderOut:
    try:
        order = svc.modify(
            order_id, ModifyOrderRequest(sl_price=req.sl_price, tp_price=req.tp_price)
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg) from exc
    except OrderGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_out(order)


@router.delete("/orders/{order_id}", response_model=OrderOut)
def cancel_order(order_id: str, svc: OrderSvcDep) -> OrderOut:
    try:
        order = svc.cancel(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(order)


@router.post("/orders/from-markup", response_model=OrderOut)
def create_from_markup(
    req: OrderFromMarkup,
    svc: OrderSvcDep,
    markups: MarkupStoreDep,
) -> OrderOut:
    markup = markups.get(req.markup_id)
    if markup is None:
        raise HTTPException(status_code=404, detail=f"Markup not found: {req.markup_id}")
    if markup.tool_id not in {"long_position", "short_position"}:
        raise HTTPException(
            status_code=400,
            detail=f"Can only arm position tools; got {markup.tool_id!r}",
        )

    side = "long" if markup.tool_id == "long_position" else "short"
    entry = _pfloat(markup.payload.get("entry"))
    sl = _pfloat(markup.payload.get("sl"))
    tp = _pfloat(markup.payload.get("tp"))
    if entry is None:
        raise HTTPException(status_code=400, detail="Markup missing 'entry' price")

    try:
        order = svc.place(
            PlaceOrderRequest(
                symbol=markup.symbol,
                side=side,
                size_usd=req.size_usd,
                entry_type="limit",
                entry_price=entry,
                sl_price=sl,
                tp_price=tp,
                leverage=req.leverage,
                slot_id=req.slot_id,
                markup_id=req.markup_id,
                source="markup",
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OrderGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Transition the markup to 'pending' linked to the order.
    markups.update(
        req.markup_id,
        {"state": "pending", "order_id": order.id},
    )
    return _to_out(order)


def _pfloat(v: object) -> float | None:
    try:
        if v is None:
            return None
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
