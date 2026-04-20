"""OutcomeSlotRunner — ticks a HIP-4 outcome slot.

Parallel to ``SlotRunner`` (perps). Reads the market's current implied
probability + pricing-model edge, emits a Decision when |edge| crosses
the slot's threshold.

Slots of kind='outcome' are plain ``Slot`` rows with two conventions:
  * ``slot.symbol`` is a market_id (``outcome:<numeric>``).
  * ``slot.strategy_params`` carries ``edge_threshold`` (default 0.03),
    ``default_vol`` (default 0.80), and ``min_size_usd`` (default 10).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.models.slot import Slot
from backend.services.audit import AuditService
from backend.services.slot_repository import SlotRepository
from engine import Decision, DecisionAction

logger = logging.getLogger(__name__)

DEFAULT_EDGE_THRESHOLD = 0.03
DEFAULT_VOL = 0.80


class _OutcomeAnalysisLike(Protocol):
    underlying: Any
    market_yes: Any
    theory: Any  # has .fair_yes
    edge_yes: Any


class _PricingModelLike(Protocol):
    def analyse(
        self,
        outcome_id: int,
        vol: float | None = ...,
        spot: float | None = ...,
        default_vol: float = ...,
    ) -> _OutcomeAnalysisLike | None: ...


@dataclass
class OutcomeSlotRunner:
    """Dataclass to match SlotRunner's constructor style."""

    repo: SlotRepository
    audit: AuditService
    pricing_model: _PricingModelLike
    on_event: Any = None

    def tick(self, slot: Slot, *, now: datetime | None = None) -> Decision:
        now = now or datetime.now(UTC)
        if slot.kind != "outcome":
            return Decision(DecisionAction.HOLD, reason=f"not an outcome slot: kind={slot.kind!r}")
        if not slot.enabled:
            return Decision(DecisionAction.HOLD, reason="slot disabled")

        outcome_id = _parse_outcome_id(slot.symbol)
        if outcome_id is None:
            return Decision(DecisionAction.HOLD, reason=f"bad outcome symbol: {slot.symbol!r}")

        params = slot.strategy_params or {}
        threshold = float(params.get("edge_threshold", DEFAULT_EDGE_THRESHOLD))
        default_vol = float(params.get("default_vol", DEFAULT_VOL))

        try:
            result = self.pricing_model.analyse(outcome_id, default_vol=default_vol)
        except Exception as exc:  # noqa: BLE001
            self.audit.log(
                "decision_rejected",
                source="outcome_slot_runner",
                slot_id=slot.id,
                symbol=slot.symbol,
                reason=f"pricing failed: {exc}",
            )
            return Decision(DecisionAction.HOLD, reason="pricing unavailable")

        if result is None:
            return Decision(DecisionAction.HOLD, reason="outcome not found or not price-binary")

        edge = _to_float(result.edge_yes)
        market_yes = _to_float(result.market_yes)
        theo = _to_float(getattr(result.theory, "fair_yes", None))

        self._emit({
            "type": "outcome_edge",
            "slot_id": slot.id,
            "market_id": slot.symbol,
            "edge_yes": edge,
            "theoretical_yes": theo,
            "market_yes": market_yes,
        })

        if edge is None or abs(edge) < threshold:
            reason = f"edge {edge:.3f} below threshold {threshold:.3f}" if edge is not None else "no edge"
            return Decision(DecisionAction.HOLD, reason=reason)

        state = self.repo.get_state(slot.id)
        current_position = state.current_position if state else None

        # Positive edge = model thinks Yes is underpriced → buy Yes (LONG).
        # Negative edge = model thinks Yes is overpriced → buy No (SHORT).
        if edge > 0:
            if current_position == "LONG":
                return Decision(DecisionAction.HOLD, reason="already long yes")
            if current_position == "SHORT":
                decision = Decision(DecisionAction.CLOSE_SHORT, reason=f"edge flipped to +{edge:.3f}")
            else:
                decision = Decision(
                    DecisionAction.OPEN_LONG,
                    reason=f"long yes on edge +{edge:.3f}",
                    strength=min(1.0, abs(edge) / 0.2),
                )
        else:
            if current_position == "SHORT":
                return Decision(DecisionAction.HOLD, reason="already short yes")
            if current_position == "LONG":
                decision = Decision(DecisionAction.CLOSE_LONG, reason=f"edge flipped to {edge:.3f}")
            else:
                decision = Decision(
                    DecisionAction.OPEN_SHORT,
                    reason=f"short yes on edge {edge:.3f}",
                    strength=min(1.0, abs(edge) / 0.2),
                )

        self.audit.log(
            "decision_emitted",
            source="outcome_slot_runner",
            slot_id=slot.id,
            strategy=slot.strategy,
            symbol=slot.symbol,
            reason=decision.reason or decision.action.value,
        )
        self._emit({
            "type": "decision",
            "slot_id": slot.id,
            "action": decision.action.value,
            "reason": decision.reason,
        })
        self.repo.upsert_state(
            slot.id,
            last_tick_at=now,
            last_decision_action=decision.action.value,
            last_signal=decision.reason or decision.action.value,
        )
        return decision

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001
            logger.exception("OutcomeSlotRunner event emit failed")


def _parse_outcome_id(symbol: str) -> int | None:
    stripped = symbol.removeprefix("outcome:") if symbol.startswith("outcome:") else symbol
    try:
        return int(stripped)
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
