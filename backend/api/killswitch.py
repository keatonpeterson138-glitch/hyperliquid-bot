"""/killswitch — always-available last-resort safety."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.kill_switch import KillSwitchService

router = APIRouter(tags=["killswitch"])


def get_kill_switch() -> KillSwitchService:
    raise HTTPException(status_code=503, detail="KillSwitchService not configured")


KillDep = Annotated[KillSwitchService, Depends(get_kill_switch)]


class ActivateRequest(BaseModel):
    confirmation: str = Field(..., description='Must equal "KILL"')
    source: str = "user"


class ActivateResponse(BaseModel):
    orders_cancelled: list[dict[str, Any]]
    positions_closed: list[dict[str, Any]]
    slots_disabled: int
    errors: list[dict[str, str]]


class StatusResponse(BaseModel):
    active: bool
    last_activated: datetime | None = None


class ResetRequest(BaseModel):
    confirmation: str = Field(..., description='Must equal "RESUME"')
    source: str = "user"


@router.post("/killswitch/activate", response_model=ActivateResponse)
def activate(req: ActivateRequest, svc: KillDep) -> ActivateResponse:
    try:
        report = svc.activate(confirmation=req.confirmation, source=req.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActivateResponse(
        orders_cancelled=report.orders_cancelled,
        positions_closed=report.positions_closed,
        slots_disabled=report.slots_disabled,
        errors=report.errors,
    )


@router.get("/killswitch/status", response_model=StatusResponse)
def status(svc: KillDep) -> StatusResponse:
    return StatusResponse(active=svc.is_active(), last_activated=svc.last_activated())


@router.post("/killswitch/reset", status_code=204)
def reset(req: ResetRequest, svc: KillDep) -> None:
    try:
        svc.reset(confirmation=req.confirmation, source=req.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
