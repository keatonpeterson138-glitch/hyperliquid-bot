"""/settings — read + patch app settings (JSON-file-backed)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.settings_store import Settings, SettingsStore

router = APIRouter(tags=["settings"])


def get_settings_store() -> SettingsStore:
    raise HTTPException(status_code=503, detail="SettingsStore not configured")


StoreDep = Annotated[SettingsStore, Depends(get_settings_store)]


class SettingsOut(BaseModel):
    testnet: bool
    email_enabled: bool
    telegram_enabled: bool
    desktop_notifications: bool
    default_stop_loss_pct: float
    default_take_profit_pct: float
    confirm_above_usd: float
    confirm_modify_pct: float
    confirm_leverage_above: int
    aggregate_exposure_cap_usd: float | None
    data_root: str
    backfill_throttle_ms: int
    cross_validate_threshold_pct: float
    duckdb_cache_mb: int
    theme: str
    density: str
    dev_mode: bool
    log_level: str
    extras: dict[str, Any] = Field(default_factory=dict)


class SettingsPatch(BaseModel):
    testnet: bool | None = None
    email_enabled: bool | None = None
    telegram_enabled: bool | None = None
    desktop_notifications: bool | None = None
    default_stop_loss_pct: float | None = None
    default_take_profit_pct: float | None = None
    confirm_above_usd: float | None = None
    confirm_modify_pct: float | None = None
    confirm_leverage_above: int | None = None
    aggregate_exposure_cap_usd: float | None = None
    data_root: str | None = None
    backfill_throttle_ms: int | None = None
    cross_validate_threshold_pct: float | None = None
    duckdb_cache_mb: int | None = None
    theme: str | None = None
    density: str | None = None
    dev_mode: bool | None = None
    log_level: str | None = None
    extras: dict[str, Any] | None = None


def _to_out(s: Settings) -> SettingsOut:
    d = asdict(s)
    # Convert inf → None for JSON clients.
    if d["aggregate_exposure_cap_usd"] == float("inf"):
        d["aggregate_exposure_cap_usd"] = None
    return SettingsOut(**d)


@router.get("/settings", response_model=SettingsOut)
def get_settings(store: StoreDep) -> SettingsOut:
    return _to_out(store.all())


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(patch: SettingsPatch, store: StoreDep) -> SettingsOut:
    data = patch.model_dump(exclude_unset=True)
    # UI sends null when clearing the cap — translate back to infinity.
    if data.get("aggregate_exposure_cap_usd") is None and "aggregate_exposure_cap_usd" in data:
        data["aggregate_exposure_cap_usd"] = float("inf")
    return _to_out(store.update(data))
