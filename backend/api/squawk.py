"""/squawk — Telegram live news feed. Polls the configured channel
every 60s; UI polls this endpoint at whatever cadence it likes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.services.telegram_squawk import TelegramSquawkService

router = APIRouter(tags=["squawk"])


def get_squawk_service() -> TelegramSquawkService:
    raise HTTPException(status_code=503, detail="TelegramSquawkService not configured")


SvcDep = Annotated[TelegramSquawkService, Depends(get_squawk_service)]


class SquawkPostOut(BaseModel):
    id: int
    channel: str
    text: str
    posted_at: datetime
    link: str | None = None


class SquawkLatestResponse(BaseModel):
    posts: list[SquawkPostOut] = Field(default_factory=list)
    status: dict[str, Any] = Field(default_factory=dict)


@router.get("/squawk/latest", response_model=SquawkLatestResponse)
def latest(svc: SvcDep, limit: int = 100) -> SquawkLatestResponse:
    # Lazy-start on first hit so we don't spawn the thread if the user
    # never opens the Squawk tab.
    svc.ensure_started()
    posts = svc.posts(limit=min(max(limit, 1), 500))
    return SquawkLatestResponse(
        posts=[
            SquawkPostOut(
                id=p.id, channel=p.channel, text=p.text,
                posted_at=p.posted_at, link=p.link,
            )
            for p in posts
        ],
        status=svc.status(),
    )


@router.post("/squawk/refresh", response_model=SquawkLatestResponse)
def refresh(svc: SvcDep) -> SquawkLatestResponse:
    svc.ensure_started()
    # Best-effort synchronous refresh — background thread is the main driver.
    try:
        svc._tick()  # noqa: SLF001 - internal but intentionally exposed for manual refresh
    except Exception:  # noqa: BLE001
        pass
    return latest(svc)
