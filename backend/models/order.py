"""Pydantic models for /orders."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OrderLegOut(BaseModel):
    id: int | None = None
    leg_type: Literal["entry", "sl", "tp"]
    exchange_order_id: str | None = None
    price: float | None = None
    status: str


class OrderOut(BaseModel):
    id: str
    symbol: str
    side: Literal["long", "short"]
    size_usd: float
    entry_type: Literal["market", "limit"]
    entry_price: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    leverage: int | None = None
    status: str
    slot_id: str | None = None
    markup_id: str | None = None
    exchange_order_id: str | None = None
    fill_price: float | None = None
    source: str = "api"
    reject_reason: str | None = None
    legs: list[OrderLegOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrderCreate(BaseModel):
    symbol: str
    side: Literal["long", "short"]
    size_usd: float = Field(gt=0)
    entry_type: Literal["market", "limit"] = "market"
    entry_price: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    leverage: int | None = None
    slot_id: str | None = None
    markup_id: str | None = None
    source: str = "api"


class OrderModify(BaseModel):
    sl_price: float | None = None
    tp_price: float | None = None


class OrderFromMarkup(BaseModel):
    markup_id: str
    size_usd: float = Field(gt=0)
    leverage: int | None = None
    slot_id: str | None = None
