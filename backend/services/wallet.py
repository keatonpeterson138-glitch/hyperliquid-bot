"""WalletService — aggregates balance, positions, P&L, fee totals, and
recent activity into a single ``GET /wallet/summary`` payload for the
sidebar Wallet tab.

Data sources:
  * Exchange (via OrderService.gateway → balance + live positions).
    If no gateway is configured (pre-vault-unlock dev), fall back to
    the simulated ``orders`` table so the UI still has something to
    show.
  * ``audit_log`` → realised-PnL + fees paid (session + all-time).
  * ``orders`` → open brackets, recent fills.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.services.audit import AuditService
from backend.services.order_repository import Order, OrderRepository

logger = logging.getLogger(__name__)


class BalanceProvider(Protocol):
    def get_balance(self) -> dict[str, Any]: ...
    def get_all_positions(self) -> list[dict[str, Any]]: ...


@dataclass
class WalletPosition:
    symbol: str
    side: str
    size_usd: float
    entry_price: float | None
    unrealised_pnl_usd: float | None


@dataclass
class WalletSummary:
    wallet_address: str | None
    usdc_balance: float | None
    total_notional_usd: float
    unrealised_pnl_usd: float
    realised_pnl_session_usd: float
    realised_pnl_all_time_usd: float
    fees_paid_all_time_usd: float
    positions: list[WalletPosition] = field(default_factory=list)
    open_orders: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class WalletService:
    def __init__(
        self,
        orders: OrderRepository,
        audit: AuditService,
        *,
        balance_provider: BalanceProvider | None = None,
    ) -> None:
        self.orders = orders
        self.audit = audit
        self.balance_provider = balance_provider

    def summary(self, *, wallet_address: str | None = None) -> WalletSummary:
        usdc_balance: float | None = None
        positions: list[WalletPosition] = []
        total_notional = 0.0
        unrealised = 0.0

        if self.balance_provider is not None:
            try:
                bal = self.balance_provider.get_balance()
                usdc_balance = _to_float(bal.get("usdc") or bal.get("balance"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("wallet balance fetch failed: %s", exc)
            try:
                raw_positions = self.balance_provider.get_all_positions()
                for p in raw_positions:
                    size = _to_float(p.get("size_usd")) or 0.0
                    entry = _to_float(p.get("entry_price"))
                    pnl = _to_float(p.get("unrealised_pnl_usd"))
                    total_notional += size
                    unrealised += pnl or 0.0
                    positions.append(WalletPosition(
                        symbol=str(p.get("symbol", "")),
                        side=str(p.get("side", "long")),
                        size_usd=size,
                        entry_price=entry,
                        unrealised_pnl_usd=pnl,
                    ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("positions fetch failed: %s", exc)

        # Fall back to local orders repo so the UI has *something* pre-unlock.
        if not positions:
            for order in self.orders.list(status="working"):
                side = order.side
                pos = WalletPosition(
                    symbol=order.symbol,
                    side=side,
                    size_usd=order.size_usd,
                    entry_price=order.fill_price or order.entry_price,
                    unrealised_pnl_usd=None,
                )
                positions.append(pos)
                total_notional += order.size_usd

        open_orders = len([o for o in self.orders.list() if o.status in {"pending", "working"}])

        # Session P&L = audit-log 'decision_executed' events since service start.
        # Simple v1 approach: sum of all 'order.filled' realised PnL rows.
        realised_session = self._realised_since(datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0))
        realised_all_time = self._realised_since(datetime(1970, 1, 1, tzinfo=UTC))
        fees_paid = self._fees_paid()

        return WalletSummary(
            wallet_address=wallet_address,
            usdc_balance=usdc_balance,
            total_notional_usd=total_notional,
            unrealised_pnl_usd=unrealised,
            realised_pnl_session_usd=realised_session,
            realised_pnl_all_time_usd=realised_all_time,
            fees_paid_all_time_usd=fees_paid,
            positions=positions,
            open_orders=open_orders,
        )

    def recent_activity(self, limit: int = 25) -> list[Order]:
        return self.orders.list()[:limit]

    def _realised_since(self, since: datetime) -> float:
        events = self.audit.query(event_types=["order.filled"], since=since, limit=10_000)
        total = 0.0
        for ev in events:
            resp = ev.exchange_response or {}
            pnl = resp.get("realised_pnl_usd") or resp.get("realised_pnl")
            if pnl is not None:
                try:
                    total += float(pnl)
                except (TypeError, ValueError):
                    continue
        return total

    def _fees_paid(self) -> float:
        events = self.audit.query(event_types=["order.filled"], limit=10_000)
        total = 0.0
        for ev in events:
            resp = ev.exchange_response or {}
            fee = resp.get("fee_usd")
            if fee is not None:
                try:
                    total += float(fee)
                except (TypeError, ValueError):
                    continue
        return total


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
