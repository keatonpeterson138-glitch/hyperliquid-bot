"""/universe — market discovery + tagging."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.models.market import (
    Market,
    RefreshResponse,
    TagRequest,
    UniverseResponse,
)
from backend.services.universe_manager import UniverseManager

router = APIRouter(tags=["universe"])


def get_universe_manager() -> UniverseManager:
    """Dependency override hook — production wiring in backend.main."""
    raise HTTPException(status_code=503, detail="UniverseManager not configured")


UniverseDep = Annotated[UniverseManager, Depends(get_universe_manager)]


@router.get("/universe", response_model=UniverseResponse)
def list_markets(
    um: UniverseDep,
    kind: str | None = None,
    category: str | None = None,
    active_only: bool = True,
) -> UniverseResponse:
    markets = um.list_markets(kind=kind, category=category, active_only=active_only)
    return UniverseResponse(markets=[Market(**m) for m in markets])


@router.get("/universe/{market_id:path}", response_model=Market)
def get_market(market_id: str, um: UniverseDep) -> Market:
    market = um.get(market_id)
    if market is None:
        raise HTTPException(status_code=404, detail=f"Market not found: {market_id}")
    return Market(**market)


@router.post("/universe/refresh", response_model=RefreshResponse)
def refresh(um: UniverseDep) -> RefreshResponse:
    result = um.refresh()
    return RefreshResponse(
        markets_total=result.markets_total,
        markets_added=result.markets_added,
        markets_reactivated=result.markets_reactivated,
        markets_deactivated=result.markets_deactivated,
    )


@router.post("/universe/{market_id:path}/tag", status_code=204)
def tag_market(market_id: str, req: TagRequest, um: UniverseDep) -> None:
    if um.get(market_id) is None:
        raise HTTPException(status_code=404, detail=f"Market not found: {market_id}")
    um.tag(market_id, req.tag)


@router.delete("/universe/{market_id:path}/tag", status_code=204)
def untag_market(market_id: str, req: TagRequest, um: UniverseDep) -> None:
    um.untag(market_id, req.tag)


@router.get("/universe/tag/{tag}", response_model=UniverseResponse)
def markets_by_tag(tag: str, um: UniverseDep) -> UniverseResponse:
    markets = um.markets_by_tag(tag)
    return UniverseResponse(markets=[Market(**m) for m in markets])
