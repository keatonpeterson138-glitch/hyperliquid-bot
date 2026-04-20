"""Pydantic models for the candles / catalog / backfill API surface."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Bar(BaseModel):
    """One OHLCV bar in JSON-friendly form."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int | None = None
    source: str | None = None


class CandlesResponse(BaseModel):
    symbol: str
    interval: str
    bar_count: int
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    bars: list[Bar]


class CatalogEntry(BaseModel):
    symbol: str
    interval: str
    earliest: datetime | None
    latest: datetime | None
    bar_count: int
    source_count: int


class CatalogResponse(BaseModel):
    entries: list[CatalogEntry]


class BackfillRequest(BaseModel):
    symbol: str
    interval: str = Field(pattern="^(1m|5m|15m|1h|4h|1d)$")
    start: datetime
    end: datetime | None = None   # defaults to now server-side
    source: str | None = None     # optional restrict
    allow_partial: bool = False
    testnet: bool = False


class BackfillResponse(BaseModel):
    symbol: str
    interval: str
    rows_written: int
    sources_used: list[str]
    errors: list[dict[str, str]] = Field(default_factory=list)
