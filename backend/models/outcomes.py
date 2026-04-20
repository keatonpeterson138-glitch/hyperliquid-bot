"""Pydantic models for HIP-4 outcome tape API surface."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class OutcomeTick(BaseModel):
    timestamp: datetime
    price: float
    volume: float
    implied_prob: float
    best_bid: float | None = None
    best_ask: float | None = None
    event_id: str | None = None
    source: str | None = None


class OutcomeTapeResponse(BaseModel):
    market_id: str
    tick_count: int
    ticks: list[OutcomeTick] = Field(default_factory=list)
