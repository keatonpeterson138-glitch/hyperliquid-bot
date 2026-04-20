"""/markets — live Hyperliquid data (mids, meta, funding).

Feeds the dashboard ticker row and anywhere else the UI wants a live
price without hitting the candle lake. Cached server-side by
``LiveMarketService`` (3s TTL on mids) so the UI can poll at 1-2s
cadence without amplifying against the exchange.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.live_market import LiveMarketService

router = APIRouter(tags=["markets"])


def get_live_market() -> LiveMarketService:
    raise HTTPException(status_code=503, detail="LiveMarketService not configured")


LiveDep = Annotated[LiveMarketService, Depends(get_live_market)]


class Ticker(BaseModel):
    symbol: str
    price: float | None = None
    as_of: datetime


class TickerResponse(BaseModel):
    tickers: list[Ticker] = Field(default_factory=list)


class MetaResponse(BaseModel):
    raw: dict[str, Any] = Field(default_factory=dict)


class FundingRow(BaseModel):
    coin: str
    funding_rate: float
    premium: float | None = None
    timestamp: datetime


class FundingResponse(BaseModel):
    symbol: str
    rows: list[FundingRow] = Field(default_factory=list)


@router.get("/markets/ticker", response_model=TickerResponse)
def get_ticker(
    svc: LiveDep,
    symbols: Annotated[str, Query(description="Comma-separated symbol list, e.g. BTC,ETH,SOL")] = "BTC,ETH,SOL,HYPE",
) -> TickerResponse:
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    snapshots = svc.tickers(syms)
    return TickerResponse(tickers=[
        Ticker(symbol=s.symbol, price=s.price, as_of=datetime.fromtimestamp(s.as_of))
        for s in snapshots
    ])


@router.get("/markets/mids", response_model=dict[str, float])
def get_all_mids(svc: LiveDep) -> dict[str, float]:
    """Full mid map across every tradable symbol. Use ``/markets/ticker``
    if you only need a few."""
    return svc.all_mids()


@router.get("/markets/meta", response_model=MetaResponse)
def get_meta(svc: LiveDep) -> MetaResponse:
    try:
        data = svc.meta()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"meta fetch failed: {exc}") from exc
    return MetaResponse(raw=data if isinstance(data, dict) else {"universe": data})


@router.get("/markets/funding", response_model=FundingResponse)
def get_funding(
    svc: LiveDep,
    symbol: Annotated[str, Query(min_length=1)],
    lookback_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> FundingResponse:
    try:
        rows = svc.funding_history(symbol, lookback_hours=lookback_hours)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"funding fetch failed: {exc}") from exc
    out: list[FundingRow] = []
    for r in rows:
        try:
            out.append(FundingRow(
                coin=str(r.get("coin", symbol)),
                funding_rate=float(r.get("fundingRate", 0.0)),
                premium=float(r["premium"]) if "premium" in r and r["premium"] is not None else None,
                timestamp=datetime.fromtimestamp(int(r.get("time", 0)) / 1000),
            ))
        except (TypeError, ValueError, KeyError):
            continue
    return FundingResponse(symbol=symbol, rows=out)
