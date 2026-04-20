"""ShadowClient — runs a slot's strategy against testnet in parallel.

Phase 2 ships the contract + plumbing so SlotRunner can opt-in via the
``shadow_enabled`` flag. The Phase 11 polish wires ``ShadowSlotRunner``
to fork-execute every tick and emit ``shadow_divergence`` events when
mainnet vs testnet decisions disagree.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.order_executor import ExchangeClient, OrderExecutor
from engine import Decision, DecisionAction

logger = logging.getLogger(__name__)


@dataclass
class ShadowState:
    """Per-slot shadow tracking — testnet position + cumulative P&L."""

    slot_id: str
    testnet_position: str | None = None
    testnet_entry_price: float | None = None
    testnet_realized_pnl: float = 0.0
    last_divergence: dict[str, Any] | None = None
    divergence_count: int = 0


@dataclass
class ShadowRunner:
    """Mirror a real SlotRunner against a testnet exchange.

    Construct with the SAME exchange client as the production runner but
    pointing at testnet. Driven by ``record(slot, mainnet_decision,
    shadow_decision)`` after each main tick.
    """

    testnet_exchange: ExchangeClient
    audit: AuditService
    executor: OrderExecutor = field(default_factory=OrderExecutor)
    on_divergence: list = field(default_factory=list)
    _states: dict[str, ShadowState] = field(default_factory=dict, init=False, repr=False)

    def state(self, slot_id: str) -> ShadowState:
        if slot_id not in self._states:
            self._states[slot_id] = ShadowState(slot_id=slot_id)
        return self._states[slot_id]

    def record(
        self,
        slot: Slot,
        mainnet_decision: Decision,
        shadow_decision: Decision,
    ) -> None:
        """Compare two decisions; execute shadow on testnet; alert on divergence."""
        if mainnet_decision.action != shadow_decision.action:
            payload = {
                "mainnet": mainnet_decision.action.value,
                "shadow": shadow_decision.action.value,
                "main_reason": mainnet_decision.reason,
                "shadow_reason": shadow_decision.reason,
            }
            state = self.state(slot.id)
            state.last_divergence = payload
            state.divergence_count += 1
            self.audit.log(
                "shadow_divergence",
                source="shadow_runner",
                slot_id=slot.id,
                strategy=slot.strategy,
                symbol=slot.symbol,
                reason=f"main={payload['mainnet']} shadow={payload['shadow']}",
            )
            for cb in self.on_divergence:
                try:
                    cb({"slot_id": slot.id, **payload})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Shadow divergence callback raised: %s", exc)

        # Execute the shadow side against testnet — fire-and-forget P&L tracking.
        if shadow_decision.is_actionable:
            result = self.executor.execute(shadow_decision, slot, self.testnet_exchange)
            if result.success:
                state = self.state(slot.id)
                if shadow_decision.action is DecisionAction.OPEN_LONG:
                    state.testnet_position = "LONG"
                    state.testnet_entry_price = result.fill_price
                elif shadow_decision.action is DecisionAction.OPEN_SHORT:
                    state.testnet_position = "SHORT"
                    state.testnet_entry_price = result.fill_price
                elif shadow_decision.action in (
                    DecisionAction.CLOSE_LONG,
                    DecisionAction.CLOSE_SHORT,
                ):
                    state.testnet_position = None
                    state.testnet_entry_price = None
