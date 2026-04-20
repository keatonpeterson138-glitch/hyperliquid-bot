"""Slot models — both the SQLite-row dataclass and Pydantic API surface."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class Slot:
    """In-process representation of a slot row."""

    id: str
    kind: str  # 'perp' | 'outcome'
    symbol: str
    strategy: str
    size_usd: float
    interval: str | None = None
    strategy_params: dict[str, Any] = field(default_factory=dict)
    leverage: int | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    enabled: bool = False
    shadow_enabled: bool = False
    trailing_sl: bool = False
    mtf_enabled: bool = True
    regime_filter: bool = False
    atr_stops: bool = False
    loss_cooldown: bool = False
    volume_confirm: bool = False
    rsi_guard: bool = False
    rsi_guard_low: float = 30.0
    rsi_guard_high: float = 70.0
    ml_model_id: str | None = None


@dataclass
class SlotState:
    slot_id: str
    last_tick_at: datetime | None = None
    last_signal: str | None = None
    last_decision_action: str | None = None
    current_position: str | None = None  # 'LONG' | 'SHORT' | None
    entry_price: float | None = None
    position_size_usd: float | None = None
    open_order_ids: list[str] = field(default_factory=list)


# ── Pydantic API models ────────────────────────────────────────────────────


class SlotCreate(BaseModel):
    kind: str = Field(default="perp", pattern="^(perp|outcome)$")
    symbol: str
    strategy: str
    size_usd: float = Field(gt=0)
    interval: str | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    leverage: int | None = Field(default=None, ge=1, le=50)
    stop_loss_pct: float | None = Field(default=None, gt=0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    enabled: bool = False
    shadow_enabled: bool = False
    trailing_sl: bool = False
    mtf_enabled: bool = True
    regime_filter: bool = False
    atr_stops: bool = False
    loss_cooldown: bool = False
    volume_confirm: bool = False
    rsi_guard: bool = False
    rsi_guard_low: float = 30.0
    rsi_guard_high: float = 70.0
    ml_model_id: str | None = None


class SlotUpdate(BaseModel):
    """Partial update — every field optional."""

    symbol: str | None = None
    strategy: str | None = None
    strategy_params: dict[str, Any] | None = None
    size_usd: float | None = Field(default=None, gt=0)
    interval: str | None = None
    leverage: int | None = Field(default=None, ge=1, le=50)
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    enabled: bool | None = None
    shadow_enabled: bool | None = None
    trailing_sl: bool | None = None
    mtf_enabled: bool | None = None
    regime_filter: bool | None = None
    atr_stops: bool | None = None
    loss_cooldown: bool | None = None
    volume_confirm: bool | None = None
    rsi_guard: bool | None = None
    rsi_guard_low: float | None = None
    rsi_guard_high: float | None = None
    ml_model_id: str | None = None


class SlotOut(BaseModel):
    id: str
    kind: str
    symbol: str
    strategy: str
    size_usd: float
    interval: str | None = None
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    leverage: int | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    enabled: bool
    shadow_enabled: bool
    trailing_sl: bool = False
    mtf_enabled: bool = True
    regime_filter: bool = False
    atr_stops: bool = False
    loss_cooldown: bool = False
    volume_confirm: bool = False
    rsi_guard: bool = False
    rsi_guard_low: float = 30.0
    rsi_guard_high: float = 70.0
    ml_model_id: str | None = None
    state: dict[str, Any] | None = None
