"""Pydantic models for /markups."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MarkupOut(BaseModel):
    id: str
    layout_id: str | None = None
    symbol: str
    interval: str | None = None
    tool_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    z: int = 0
    locked: bool = False
    hidden: bool = False
    state: str = "draft"
    order_id: str | None = None


class MarkupCreate(BaseModel):
    symbol: str
    tool_id: str
    payload: dict[str, Any]
    interval: str | None = None
    layout_id: str | None = None
    style: dict[str, Any] | None = None
    z: int = 0


class MarkupUpdate(BaseModel):
    payload: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    z: int | None = None
    locked: bool | None = None
    hidden: bool | None = None
    state: str | None = None
    order_id: str | None = None
