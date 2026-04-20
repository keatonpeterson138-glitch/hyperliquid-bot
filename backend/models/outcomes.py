"""Pydantic models for HIP-4 outcome API surface: tape + edge."""
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


class OutcomeEdge(BaseModel):
    """Pricing-model edge snapshot for a single HIP-4 outcome.

    ``edge_yes = theoretical_prob_yes - market_yes`` — positive means the
    market is underpricing the Yes token vs the model. Kelly sizing uses
    ``edge_yes`` directly against the market odds.
    """

    market_id: str
    underlying: str | None = None
    target_price: float | None = None
    t_years: float | None = None
    spot: float | None = None
    vol_used: float | None = None
    vol_source: str | None = None  # 'provided' | 'historical' | 'default'
    theoretical_prob_yes: float | None = None
    theoretical_prob_no: float | None = None
    market_yes: float | None = None
    market_no: float | None = None
    edge_yes: float | None = None
    edge_no: float | None = None
    implied_vol: float | None = None


class OutcomeOrderBookLevel(BaseModel):
    price: float
    size: float


class OutcomeOrderBook(BaseModel):
    market_id: str
    bids: list[OutcomeOrderBookLevel] = Field(default_factory=list)
    asks: list[OutcomeOrderBookLevel] = Field(default_factory=list)
    timestamp: datetime
