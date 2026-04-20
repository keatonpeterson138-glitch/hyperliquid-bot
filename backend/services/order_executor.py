"""OrderExecutor — translates ``Decision`` into exchange calls.

The exchange interface is a Protocol so tests inject a fake. Production
wires in ``core.exchange.HyperliquidClient``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from backend.models.slot import Slot
from engine import Decision, DecisionAction

logger = logging.getLogger(__name__)


class ExchangeClient(Protocol):
    def get_market_price(self, symbol: str) -> float | None: ...
    def place_market_order(
        self, symbol: str, is_buy: bool, size_usd: float, leverage: int
    ) -> dict[str, Any]: ...
    def close_position(self, symbol: str, dex: str = "") -> dict[str, Any]: ...


@dataclass
class ExecutionResult:
    decision: Decision
    success: bool
    order_id: str | None = None
    fill_price: float | None = None
    raw_response: dict[str, Any] | None = None
    error: str | None = None


class OrderExecutor:
    def execute(
        self, decision: Decision, slot: Slot, exchange: ExchangeClient
    ) -> ExecutionResult:
        try:
            if decision.action is DecisionAction.OPEN_LONG:
                resp = exchange.place_market_order(
                    symbol=slot.symbol,
                    is_buy=True,
                    size_usd=slot.size_usd,
                    leverage=slot.leverage or 1,
                )
                return _success(decision, resp)

            if decision.action is DecisionAction.OPEN_SHORT:
                resp = exchange.place_market_order(
                    symbol=slot.symbol,
                    is_buy=False,
                    size_usd=slot.size_usd,
                    leverage=slot.leverage or 1,
                )
                return _success(decision, resp)

            if decision.action in (DecisionAction.CLOSE_LONG, DecisionAction.CLOSE_SHORT):
                dex = _dex_of(slot.symbol)
                resp = exchange.close_position(slot.symbol, dex=dex)
                return _success(decision, resp)

            # HOLD shouldn't end up here (caller checks is_actionable first),
            # but be defensive.
            return ExecutionResult(decision=decision, success=False, error="HOLD has nothing to execute")

        except Exception as exc:  # noqa: BLE001
            logger.error("OrderExecutor failed for slot %s action %s: %s", slot.id, decision.action, exc)
            return ExecutionResult(decision=decision, success=False, error=str(exc))


def _dex_of(symbol: str) -> str:
    return symbol.split(":", 1)[0] if ":" in symbol else ""


def _success(decision: Decision, resp: dict[str, Any]) -> ExecutionResult:
    return ExecutionResult(
        decision=decision,
        success=True,
        order_id=str(resp.get("order_id") or resp.get("oid") or ""),
        fill_price=_maybe_float(resp.get("fill_price") or resp.get("avg_price")),
        raw_response=resp,
    )


def _maybe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
