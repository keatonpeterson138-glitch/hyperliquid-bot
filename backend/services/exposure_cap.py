"""Aggregate exposure cap — blocks new positions that would push total
open notional above a configurable ceiling.

Lives in-process; the cap itself is persisted in the Settings JSON file
(Phase 11) so it survives restarts. Default is ``float('inf')`` (no cap).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CapCheckResult:
    allowed: bool
    current_exposure_usd: float
    cap_usd: float
    reason: str = ""

    @property
    def headroom_usd(self) -> float:
        return max(0.0, self.cap_usd - self.current_exposure_usd)


class ExposureCapService:
    def __init__(self, cap_usd: float = float("inf")) -> None:
        self.cap_usd = cap_usd

    def set_cap(self, cap_usd: float) -> None:
        if cap_usd < 0:
            raise ValueError("cap_usd must be non-negative")
        self.cap_usd = cap_usd

    def check(
        self,
        *,
        prospective_size_usd: float,
        open_positions: Iterable[dict],
    ) -> CapCheckResult:
        """Returns allowed=False when accepting ``prospective_size_usd`` would
        push aggregate notional above the cap.

        ``open_positions`` is any iterable of dicts with a ``size_usd`` key —
        the runner passes in slot-state rows or live exchange positions."""
        current = sum(float(p.get("size_usd") or 0.0) for p in open_positions)
        projected = current + max(0.0, prospective_size_usd)
        if projected > self.cap_usd:
            return CapCheckResult(
                allowed=False,
                current_exposure_usd=current,
                cap_usd=self.cap_usd,
                reason=(
                    f"exposure cap exceeded: "
                    f"${current:.2f} + ${prospective_size_usd:.2f} > ${self.cap_usd:.2f}"
                ),
            )
        return CapCheckResult(
            allowed=True,
            current_exposure_usd=current,
            cap_usd=self.cap_usd,
        )

    def current_exposure(self, open_positions: Iterable[dict]) -> float:
        return sum(float(p.get("size_usd") or 0.0) for p in open_positions)
