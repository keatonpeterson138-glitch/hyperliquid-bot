"""Pydantic models for /audit."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: int
    ts: datetime
    event_type: str
    source: str
    slot_id: str | None = None
    strategy: str | None = None
    symbol: str | None = None
    side: str | None = None
    size_usd: float | None = None
    price: float | None = None
    reason: str | None = None
    exchange_response: dict[str, Any] | None = None


class AuditResponse(BaseModel):
    total: int
    events: list[AuditEventOut]
