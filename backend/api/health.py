"""/health — minimal liveness probe.

Used by:
- The Tauri shell to detect the sidecar is up before issuing real requests.
- CI smoke tests.
- Local dev (`curl localhost:<port>/health`).
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="hyperliquid-bot-backend", version="0.2.0")
