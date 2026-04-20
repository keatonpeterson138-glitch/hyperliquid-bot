"""OrderService — places/modifies/cancels bracket orders.

Sits above ``OrderRepository`` (state) and the exchange gateway (action).
Tests inject a ``FakeExchangeGateway``; production wires in a client
backed by ``core.exchange.HyperliquidClient`` once the vault is unlocked.

A "bracket" is entry + optional SL + optional TP. Entry can be market
(fills immediately, SL/TP are placed as trigger orders after fill) or
limit (placed first, SL/TP placed on fill callback).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.services.audit import AuditService
from backend.services.markup_store import MarkupStore
from backend.services.order_repository import Order, OrderRepository

logger = logging.getLogger(__name__)


class OrderGatewayError(RuntimeError):
    """Exchange rejected the order — passed up as 400/502 by the API."""


class ExchangeGateway(Protocol):
    """Subset of the exchange client used by OrderService.

    ``place_entry`` returns a dict with at least ``exchange_order_id``
    and optionally ``fill_price`` (for market fills).
    ``place_trigger`` places an SL/TP trigger tied to an open position.
    """

    def place_entry(
        self,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        leverage: int | None,
        entry_type: str,
        entry_price: float | None,
    ) -> dict[str, Any]: ...

    def place_trigger(
        self,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        trigger_price: float,
        leg_type: str,  # 'sl' | 'tp'
    ) -> dict[str, Any]: ...

    def cancel(self, *, symbol: str, exchange_order_id: str) -> dict[str, Any]: ...

    def modify_trigger(
        self,
        *,
        symbol: str,
        exchange_order_id: str,
        trigger_price: float,
    ) -> dict[str, Any]: ...


@dataclass
class PlaceOrderRequest:
    symbol: str
    side: str
    size_usd: float
    entry_type: str = "market"
    entry_price: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    leverage: int | None = None
    slot_id: str | None = None
    markup_id: str | None = None
    source: str = "api"


@dataclass
class ModifyOrderRequest:
    sl_price: float | None = None
    tp_price: float | None = None


@dataclass
class OrderFillEvent:
    order_id: str
    fill_price: float
    filled_at: str
    extra: dict[str, Any] = field(default_factory=dict)


class OrderService:
    def __init__(
        self,
        repo: OrderRepository,
        gateway: ExchangeGateway | None,
        *,
        audit: AuditService | None = None,
        markup_store: MarkupStore | None = None,
    ) -> None:
        self.repo = repo
        self.gateway = gateway
        self.audit = audit
        self.markup_store = markup_store

    # ── Public API ─────────────────────────────────────────────────────

    def place(self, req: PlaceOrderRequest) -> Order:
        self._validate(req)
        order = self.repo.create(
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

        if self.gateway is None:
            # Dev mode: no gateway wired. Mark pending and return — user can
            # still see the order in the UI and modify/cancel it locally.
            self._audit("order.placed_local", order)
            return order

        try:
            entry_resp = self.gateway.place_entry(
                symbol=req.symbol,
                side=req.side,
                size_usd=req.size_usd,
                leverage=req.leverage,
                entry_type=req.entry_type,
                entry_price=req.entry_price,
            )
        except Exception as exc:  # noqa: BLE001
            self.repo.update_status(order.id, "rejected", reject_reason=str(exc))
            self._audit("order.rejected", order, reason=str(exc))
            raise OrderGatewayError(str(exc)) from exc

        entry_oid = str(entry_resp.get("exchange_order_id") or "")
        fill_price = _maybe_float(entry_resp.get("fill_price"))
        self.repo.add_leg(order.id, "entry", exchange_order_id=entry_oid, price=fill_price)

        # Market fills immediately → place SL/TP triggers now.
        # Limit orders: SL/TP get placed by the fill callback.
        if req.entry_type == "market" and fill_price is not None:
            self.repo.update_status(
                order.id,
                "filled",
                exchange_order_id=entry_oid,
                fill_price=fill_price,
            )
            self._place_triggers(order.id, req)
            # After triggers, the bracket is 'working' (entry filled, SL+TP live).
            self.repo.update_status(order.id, "working")
        else:
            self.repo.update_status(order.id, "working", exchange_order_id=entry_oid)

        updated = self.repo.get(order.id)
        assert updated is not None
        self._audit("order.placed", updated)
        self._write_fill_markup(updated, fill_price)
        return updated

    def modify(self, order_id: str, req: ModifyOrderRequest) -> Order:
        order = self.repo.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        if order.status not in {"pending", "working"}:
            raise ValueError(f"Cannot modify order in status {order.status!r}")

        if self.gateway is not None:
            self._modify_trigger_leg(order, "sl", req.sl_price)
            self._modify_trigger_leg(order, "tp", req.tp_price)

        updated = self.repo.update_prices(order_id, sl_price=req.sl_price, tp_price=req.tp_price)
        assert updated is not None
        self._audit("order.modified", updated, changes={
            "sl_price": req.sl_price, "tp_price": req.tp_price,
        })
        return updated

    def cancel(self, order_id: str) -> Order:
        order = self.repo.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        if order.status in {"cancelled", "closed", "rejected"}:
            return order

        if self.gateway is not None:
            for leg in order.legs:
                if leg.exchange_order_id and leg.status == "working":
                    try:
                        self.gateway.cancel(
                            symbol=order.symbol,
                            exchange_order_id=leg.exchange_order_id,
                        )
                        if leg.id is not None:
                            self.repo.update_leg(leg.id, status="cancelled")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Cancel leg %s (%s) failed: %s", leg.id, leg.leg_type, exc
                        )

        updated = self.repo.update_status(order_id, "cancelled")
        assert updated is not None
        self._audit("order.cancelled", updated)
        return updated

    def on_fill(self, event: OrderFillEvent) -> None:
        """External fill callback (from TradeEngine's stream). Creates a
        fill_marker markup tied to the order's markup_id (if any)."""
        order = self.repo.get(event.order_id)
        if order is None:
            return
        self.repo.update_status(
            event.order_id,
            "filled",
            fill_price=event.fill_price,
        )
        self._write_fill_markup(order, event.fill_price)
        self._audit("order.filled", order, fill_price=event.fill_price)

    # ── Internals ─────────────────────────────────────────────────────

    def _place_triggers(self, order_id: str, req: PlaceOrderRequest) -> None:
        assert self.gateway is not None
        for leg_type, price in (("sl", req.sl_price), ("tp", req.tp_price)):
            if price is None:
                continue
            try:
                resp = self.gateway.place_trigger(
                    symbol=req.symbol,
                    side=req.side,
                    size_usd=req.size_usd,
                    trigger_price=price,
                    leg_type=leg_type,
                )
                self.repo.add_leg(
                    order_id,
                    leg_type,
                    exchange_order_id=str(resp.get("exchange_order_id") or ""),
                    price=price,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Trigger %s failed: %s", leg_type, exc)
                self.repo.add_leg(order_id, leg_type, price=price, status="cancelled")

    def _modify_trigger_leg(self, order: Order, leg_type: str, new_price: float | None) -> None:
        if new_price is None or self.gateway is None:
            return
        leg = next(
            (lg for lg in order.legs if lg.leg_type == leg_type and lg.status == "working"),
            None,
        )
        if leg is None or not leg.exchange_order_id:
            return
        try:
            self.gateway.modify_trigger(
                symbol=order.symbol,
                exchange_order_id=leg.exchange_order_id,
                trigger_price=new_price,
            )
            if leg.id is not None:
                self.repo.update_leg(leg.id, price=new_price)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Modify %s leg failed: %s", leg_type, exc)

    def _write_fill_markup(self, order: Order, fill_price: float | None) -> None:
        if fill_price is None or self.markup_store is None:
            return
        side_str = "buy" if order.side == "long" else "sell"
        self.markup_store.create(
            symbol=order.symbol,
            tool_id="fill_marker",
            payload={"price": fill_price, "side": side_str, "order_id": order.id},
        )

    def _audit(self, event_type: str, order: Order, **extra: Any) -> None:
        if self.audit is None:
            return
        try:
            self.audit.log(
                event_type,
                source="order_service",
                slot_id=order.slot_id,
                symbol=order.symbol,
                side=order.side,
                size_usd=order.size_usd,
                price=extra.pop("fill_price", None) or order.fill_price or order.entry_price,
                reason=extra.pop("reason", None),
                exchange_response={"order_id": order.id, "status": order.status, **extra},
            )
        except Exception:  # noqa: BLE001
            logger.exception("audit write failed for %s", event_type)

    @staticmethod
    def _validate(req: PlaceOrderRequest) -> None:
        if req.size_usd <= 0:
            raise ValueError("size_usd must be > 0")
        if req.side == "long":
            if req.sl_price is not None and req.entry_price is not None and req.sl_price >= req.entry_price:
                raise ValueError("long SL must be below entry")
            if req.tp_price is not None and req.entry_price is not None and req.tp_price <= req.entry_price:
                raise ValueError("long TP must be above entry")
        elif req.side == "short":
            if req.sl_price is not None and req.entry_price is not None and req.sl_price <= req.entry_price:
                raise ValueError("short SL must be above entry")
            if req.tp_price is not None and req.entry_price is not None and req.tp_price >= req.entry_price:
                raise ValueError("short TP must be below entry")


def _maybe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
