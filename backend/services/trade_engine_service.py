"""TradeEngineService — orchestrates SlotRunner instances.

In v1 the orchestrator is sync: callers (or the eventual scheduler in
P2.7) drive ``tick()`` per slot at their own cadence. The service
focuses on slot lookup, kill-switch checks, and broadcasting events.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.models.slot import Slot
from backend.services.kill_switch import KillSwitchService
from backend.services.slot_repository import SlotRepository
from backend.services.slot_runner import SlotRunner
from engine import Decision, DecisionAction

logger = logging.getLogger(__name__)


class TradeEngineService:
    def __init__(
        self,
        repo: SlotRepository,
        runner: SlotRunner,
        *,
        kill_switch: KillSwitchService | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo = repo
        self.runner = runner
        self.kill_switch = kill_switch
        self.on_event = on_event

    # ── Slot lookup ────────────────────────────────────────────────────────

    def list_slots(self, *, enabled_only: bool = False) -> list[Slot]:
        return self.repo.list_all(enabled_only=enabled_only)

    def get_slot(self, slot_id: str) -> Slot | None:
        return self.repo.get(slot_id)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start_slot(self, slot_id: str) -> Slot | None:
        slot = self.repo.get(slot_id)
        if slot is None:
            return None
        if not slot.enabled:
            self.repo.update(slot_id, {"enabled": True})
        slot = self.repo.get(slot_id)
        if self.on_event and slot is not None:
            self._safe_emit({"type": "slot_started", "slot_id": slot.id})
        return slot

    def stop_slot(self, slot_id: str) -> Slot | None:
        slot = self.repo.get(slot_id)
        if slot is None:
            return None
        if slot.enabled:
            self.repo.update(slot_id, {"enabled": False})
        slot = self.repo.get(slot_id)
        if self.on_event and slot is not None:
            self._safe_emit({"type": "slot_stopped", "slot_id": slot.id})
        return slot

    def stop_all(self) -> int:
        count = 0
        for slot in self.repo.list_all(enabled_only=True):
            self.repo.update(slot.id, {"enabled": False})
            self._safe_emit({"type": "slot_stopped", "slot_id": slot.id})
            count += 1
        return count

    # ── Tick ───────────────────────────────────────────────────────────────

    def tick(self, slot_id: str) -> Decision:
        slot = self.repo.get(slot_id)
        if slot is None:
            return Decision(DecisionAction.HOLD, reason=f"unknown slot {slot_id}")
        if self.kill_switch is not None and self.kill_switch.is_active():
            return Decision(DecisionAction.HOLD, reason="kill switch active")
        return self.runner.tick(slot)

    def tick_all_enabled(self) -> dict[str, Decision]:
        out: dict[str, Decision] = {}
        if self.kill_switch is not None and self.kill_switch.is_active():
            return out
        for slot in self.repo.list_all(enabled_only=True):
            out[slot.id] = self.runner.tick(slot)
        return out

    # ── Helpers ────────────────────────────────────────────────────────────

    def _safe_emit(self, event: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.exception("TradeEngineService event callback raised: %s", exc)
