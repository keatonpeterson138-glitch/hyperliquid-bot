"""/bootstrap — macro seed dataset progress + manual re-trigger.

The backend auto-starts the seed on first launch when the lake is empty
for the canonical set (S&P 500, Nasdaq, WTI, gold, silver, DXY, BTC,
ETH, SOL). This endpoint exposes progress for the Dashboard bar and a
manual re-trigger for "I want to re-pull".
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from backend.services.macro_seed import MacroSeedService

router = APIRouter(tags=["bootstrap"])


def get_macro_seed() -> MacroSeedService:
    raise HTTPException(status_code=503, detail="MacroSeedService not configured")


SeedDep = Annotated[MacroSeedService, Depends(get_macro_seed)]


@router.get("/bootstrap/status")
def status(svc: SeedDep) -> dict[str, Any]:
    return svc.status()


@router.post("/bootstrap/start")
def start(svc: SeedDep) -> dict[str, Any]:
    svc.ensure_started()
    return svc.status()
