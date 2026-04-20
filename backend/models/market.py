"""Pydantic models for Market + MarketTag API surface."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Market(BaseModel):
    id: str
    kind: str  # 'perp' | 'outcome'
    symbol: str
    dex: str = ""
    base: str | None = None
    category: str | None = None
    subcategory: str | None = None
    max_leverage: int | None = None
    sz_decimals: int | None = None
    tick_size: float | None = None
    min_size: float | None = None
    resolution_date: datetime | None = None
    bounds: dict | None = None
    active: bool = True
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class TagRequest(BaseModel):
    tag: str


class RefreshResponse(BaseModel):
    markets_total: int
    markets_added: int
    markets_reactivated: int
    markets_deactivated: int


class UniverseResponse(BaseModel):
    markets: list[Market]
