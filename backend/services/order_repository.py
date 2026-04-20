"""OrderRepository — SQLite persistence for bracket orders.

Every order placed via ``/orders`` lives here with its per-leg exchange
ids. Slots and markups reference orders via FK so the UI can trace a
drawing → order → fills without a join gymnastics.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.db.app_db import AppDB


@dataclass
class OrderLeg:
    id: int | None
    order_id: str
    leg_type: str                # 'entry' | 'sl' | 'tp'
    exchange_order_id: str | None = None
    price: float | None = None
    status: str = "working"      # 'working' | 'filled' | 'cancelled'


@dataclass
class Order:
    id: str
    symbol: str
    side: str                    # 'long' | 'short'
    size_usd: float
    entry_type: str              # 'market' | 'limit'
    entry_price: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    leverage: int | None = None
    status: str = "pending"
    slot_id: str | None = None
    markup_id: str | None = None
    exchange_order_id: str | None = None
    fill_price: float | None = None
    source: str = "api"
    reject_reason: str | None = None
    legs: list[OrderLeg] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


VALID_STATUSES = {"pending", "working", "filled", "closed", "cancelled", "rejected"}
VALID_SIDES = {"long", "short"}
VALID_ENTRY_TYPES = {"market", "limit"}


def _row_to_order(row: Any, legs: list[OrderLeg]) -> Order:
    return Order(
        id=row["id"],
        symbol=row["symbol"],
        side=row["side"],
        size_usd=float(row["size_usd"]),
        entry_type=row["entry_type"],
        entry_price=row["entry_price"],
        sl_price=row["sl_price"],
        tp_price=row["tp_price"],
        leverage=row["leverage"],
        status=row["status"],
        slot_id=row["slot_id"],
        markup_id=row["markup_id"],
        exchange_order_id=row["exchange_order_id"],
        fill_price=row["fill_price"],
        source=row["source"] or "api",
        reject_reason=row["reject_reason"],
        legs=list(legs),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_leg(row: Any) -> OrderLeg:
    return OrderLeg(
        id=row["id"],
        order_id=row["order_id"],
        leg_type=row["leg_type"],
        exchange_order_id=row["exchange_order_id"],
        price=row["price"],
        status=row["status"],
    )


class OrderRepository:
    def __init__(self, db: AppDB) -> None:
        self.db = db

    # ── Writes ──────────────────────────────────────────────────────────

    def create(
        self,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        entry_type: str,
        entry_price: float | None = None,
        sl_price: float | None = None,
        tp_price: float | None = None,
        leverage: int | None = None,
        slot_id: str | None = None,
        markup_id: str | None = None,
        source: str = "api",
    ) -> Order:
        if side not in VALID_SIDES:
            raise ValueError(f"Invalid side: {side!r}")
        if entry_type not in VALID_ENTRY_TYPES:
            raise ValueError(f"Invalid entry_type: {entry_type!r}")
        if entry_type == "limit" and entry_price is None:
            raise ValueError("limit orders require entry_price")

        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO orders(
                    id, slot_id, markup_id, symbol, side, size_usd, leverage,
                    entry_type, entry_price, sl_price, tp_price, status, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    order_id, slot_id, markup_id, symbol, side, size_usd, leverage,
                    entry_type, entry_price, sl_price, tp_price, source,
                ),
            )
        return self.get(order_id)  # type: ignore[return-value]

    def update_status(
        self,
        order_id: str,
        status: str,
        *,
        exchange_order_id: str | None = None,
        fill_price: float | None = None,
        reject_reason: str | None = None,
    ) -> Order | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status!r}")
        cols = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, datetime.now(UTC)]
        if exchange_order_id is not None:
            cols.append("exchange_order_id = ?")
            params.append(exchange_order_id)
        if fill_price is not None:
            cols.append("fill_price = ?")
            params.append(fill_price)
        if reject_reason is not None:
            cols.append("reject_reason = ?")
            params.append(reject_reason)
        params.append(order_id)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE orders SET {', '.join(cols)} WHERE id = ?", params
            )
        return self.get(order_id)

    def update_prices(
        self,
        order_id: str,
        *,
        sl_price: float | None = None,
        tp_price: float | None = None,
    ) -> Order | None:
        cols: list[str] = []
        params: list[Any] = []
        if sl_price is not None:
            cols.append("sl_price = ?")
            params.append(sl_price)
        if tp_price is not None:
            cols.append("tp_price = ?")
            params.append(tp_price)
        if not cols:
            return self.get(order_id)
        cols.append("updated_at = ?")
        params.append(datetime.now(UTC))
        params.append(order_id)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE orders SET {', '.join(cols)} WHERE id = ?", params
            )
        return self.get(order_id)

    def add_leg(
        self,
        order_id: str,
        leg_type: str,
        *,
        exchange_order_id: str | None = None,
        price: float | None = None,
        status: str = "working",
    ) -> OrderLeg:
        if leg_type not in {"entry", "sl", "tp"}:
            raise ValueError(f"Invalid leg_type: {leg_type!r}")
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO order_legs(order_id, leg_type, exchange_order_id, price, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order_id, leg_type, exchange_order_id, price, status),
            )
            leg_id = cur.lastrowid
        return OrderLeg(
            id=leg_id,
            order_id=order_id,
            leg_type=leg_type,
            exchange_order_id=exchange_order_id,
            price=price,
            status=status,
        )

    def update_leg(
        self,
        leg_id: int,
        *,
        status: str | None = None,
        price: float | None = None,
        exchange_order_id: str | None = None,
    ) -> None:
        cols: list[str] = []
        params: list[Any] = []
        if status is not None:
            cols.append("status = ?")
            params.append(status)
        if price is not None:
            cols.append("price = ?")
            params.append(price)
        if exchange_order_id is not None:
            cols.append("exchange_order_id = ?")
            params.append(exchange_order_id)
        if not cols:
            return
        cols.append("updated_at = ?")
        params.append(datetime.now(UTC))
        params.append(leg_id)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE order_legs SET {', '.join(cols)} WHERE id = ?", params
            )

    # ── Reads ───────────────────────────────────────────────────────────

    def get(self, order_id: str) -> Order | None:
        row = self.db.fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
        if row is None:
            return None
        leg_rows = self.db.fetchall(
            "SELECT * FROM order_legs WHERE order_id = ? ORDER BY id",
            (order_id,),
        )
        return _row_to_order(row, [_row_to_leg(r) for r in leg_rows])

    def list(
        self,
        *,
        slot_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        markup_id: str | None = None,
    ) -> list[Order]:
        clauses: list[str] = []
        params: list[Any] = []
        if slot_id is not None:
            clauses.append("slot_id = ?")
            params.append(slot_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if markup_id is not None:
            clauses.append("markup_id = ?")
            params.append(markup_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.fetchall(
            f"SELECT * FROM orders{where} ORDER BY created_at DESC",
            tuple(params),
        )
        out: list[Order] = []
        for row in rows:
            leg_rows = self.db.fetchall(
                "SELECT * FROM order_legs WHERE order_id = ? ORDER BY id",
                (row["id"],),
            )
            out.append(_row_to_order(row, [_row_to_leg(r) for r in leg_rows]))
        return out

    def open_orders_for(self, symbol: str) -> list[Order]:
        return [o for o in self.list(symbol=symbol) if o.status in {"pending", "working"}]

    def link_markup(self, order_id: str, markup_id: str | None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE orders SET markup_id = ?, updated_at = ? WHERE id = ?",
                (markup_id, datetime.now(UTC), order_id),
            )
