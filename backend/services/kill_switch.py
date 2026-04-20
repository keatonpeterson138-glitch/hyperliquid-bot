"""KillSwitchService — "flatten everything NOW".

One button / one keyboard shortcut that:
1. Cancels every open order.
2. Closes every open position.
3. Disables every slot so nothing restarts.
4. Audits every step.

Operator confirms by typing ``"KILL"`` in the request body (fat-finger
guard). The service is idempotent — double activation is a safe no-op.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.db.app_db import AppDB
from backend.services.audit import AuditService

logger = logging.getLogger(__name__)


class EmergencyExchange(Protocol):
    """Subset of ``HyperliquidClient`` that the kill switch uses."""

    def cancel_all(self) -> list[dict[str, Any]]: ...
    def get_all_positions(self) -> list[dict[str, Any]]: ...
    def close_position(self, symbol: str, dex: str = "") -> dict[str, Any]: ...


@dataclass
class KillSwitchReport:
    orders_cancelled: list[dict[str, Any]] = field(default_factory=list)
    positions_closed: list[dict[str, Any]] = field(default_factory=list)
    slots_disabled: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


class KillSwitchService:
    CONFIRMATION_PHRASE = "KILL"
    RESET_CONFIRMATION = "RESUME"

    def __init__(
        self,
        exchange: EmergencyExchange,
        db: AppDB,
        audit: AuditService,
        *,
        on_activated: list | None = None,
    ) -> None:
        self.exchange = exchange
        self.db = db
        self.audit = audit
        self._active: bool = False
        self._last_activated: datetime | None = None
        self._callbacks = list(on_activated or [])

    # ── State ──────────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        return self._active

    def last_activated(self) -> datetime | None:
        return self._last_activated

    # ── Activation ─────────────────────────────────────────────────────────

    def activate(
        self,
        *,
        confirmation: str,
        source: str = "user",
    ) -> KillSwitchReport:
        if confirmation != self.CONFIRMATION_PHRASE:
            raise ValueError(
                f"Kill-switch confirmation must be '{self.CONFIRMATION_PHRASE}'"
            )
        if self._active:
            # Double-activation is a safe no-op.
            return KillSwitchReport()

        self.audit.log(
            "kill_switch_activated",
            source=source,
            reason="requested",
        )
        report = KillSwitchReport()

        # Step 1: cancel all open orders.
        try:
            cancelled = self.exchange.cancel_all()
            report.orders_cancelled = list(cancelled or [])
            self.audit.log(
                "kill_switch_step",
                source=source,
                reason=f"cancel_all ok: {len(report.orders_cancelled)} orders",
            )
        except Exception as exc:  # noqa: BLE001
            report.errors.append({"step": "cancel_all", "error": str(exc)})
            self.audit.log(
                "kill_switch_step",
                source=source,
                reason=f"cancel_all failed: {exc}",
            )

        # Step 2: close every open position.
        try:
            positions = self.exchange.get_all_positions()
        except Exception as exc:  # noqa: BLE001
            positions = []
            report.errors.append({"step": "get_all_positions", "error": str(exc)})

        for pos in positions or []:
            symbol = pos.get("symbol") or pos.get("coin") or ""
            dex = pos.get("dex", "")
            try:
                result = self.exchange.close_position(symbol, dex)
                report.positions_closed.append({"symbol": symbol, "dex": dex, "result": result})
                self.audit.log(
                    "kill_switch_step",
                    source=source,
                    symbol=symbol,
                    reason="position closed",
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append(
                    {"step": "close_position", "symbol": symbol, "error": str(exc)}
                )
                self.audit.log(
                    "kill_switch_step",
                    source=source,
                    symbol=symbol,
                    reason=f"close failed: {exc}",
                )

        # Step 3: disable every slot.
        try:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    "UPDATE slots SET enabled = 0, updated_at = ? WHERE enabled = 1",
                    (datetime.now(UTC),),
                )
                report.slots_disabled = cursor.rowcount or 0
            self.audit.log(
                "kill_switch_step",
                source=source,
                reason=f"{report.slots_disabled} slot(s) disabled",
            )
        except Exception as exc:  # noqa: BLE001
            report.errors.append({"step": "disable_slots", "error": str(exc)})

        self._active = True
        self._last_activated = datetime.now(UTC)

        # Notify listeners (e.g., StreamHub broadcast; wired in P2.7).
        for cb in self._callbacks:
            try:
                cb(report)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Kill-switch callback raised: %s", exc)

        return report

    def reset(self, *, confirmation: str, source: str = "user") -> None:
        if confirmation != self.RESET_CONFIRMATION:
            raise ValueError(
                f"Kill-switch reset confirmation must be '{self.RESET_CONFIRMATION}'"
            )
        self._active = False
        self.audit.log("kill_switch_reset", source=source)
