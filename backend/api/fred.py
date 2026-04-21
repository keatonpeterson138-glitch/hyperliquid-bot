"""/fred — browse + pull Federal Reserve Economic Data series.

Complements the FREDSource adapter (which fits into SourceRouter). These
endpoints give the UI a direct path for browsing + charting without
needing to go through the Parquet lake.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.credentials_store import CredentialsStore
from backend.services.sources.fred_source import POPULAR_SERIES, FREDSource

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fred"])


def get_credentials_for_fred() -> CredentialsStore:
    raise HTTPException(status_code=503, detail="CredentialsStore not configured")


CredsDep = Annotated[CredentialsStore, Depends(get_credentials_for_fred)]


class FREDObservation(BaseModel):
    timestamp: datetime
    value: float


class FREDSeriesInfo(BaseModel):
    id: str
    name: str
    category: str | None = None
    units: str | None = None
    frequency: str | None = None
    observation_start: str | None = None
    observation_end: str | None = None
    last_updated: str | None = None


class FREDSeriesResponse(BaseModel):
    series_id: str
    observations: list[FREDObservation] = Field(default_factory=list)


@router.get("/fred/popular", response_model=list[FREDSeriesInfo])
def popular() -> list[FREDSeriesInfo]:
    """Curated high-signal macro/rates/inflation series. No key required
    — this is just the curated list, fetching still needs a key."""
    return [
        FREDSeriesInfo(id=s["id"], name=s["name"], category=s["category"])
        for s in POPULAR_SERIES
    ]


@router.get("/fred/series/{series_id}", response_model=FREDSeriesResponse)
def series(
    series_id: str,
    creds: CredsDep,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> FREDSeriesResponse:
    end = to or datetime.now(UTC)
    start = from_ts or (end - timedelta(days=365 * 20))
    src = FREDSource(credentials=creds)
    try:
        frame = src.fetch_candles(series_id, "1d", start, end)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"FRED fetch failed: {exc}") from exc
    # FREDSource returns a CandleFrame (not a DataFrame); the rows live on .bars.
    obs = [
        FREDObservation(timestamp=row.timestamp, value=float(row.close))
        for row in frame.bars.itertuples(index=False)
    ]
    return FREDSeriesResponse(series_id=series_id, observations=obs)


@router.get("/fred/search", response_model=list[FREDSeriesInfo])
def search(
    creds: CredsDep,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[FREDSeriesInfo]:
    src = FREDSource(credentials=creds)
    items = src.search_series(q, limit=limit)
    return [FREDSeriesInfo(**_pick(item)) for item in items]


def _pick(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d.get("id", ""),
        "name": d.get("name", ""),
        "category": d.get("category"),
        "units": d.get("units"),
        "frequency": d.get("frequency"),
        "observation_start": d.get("observation_start"),
        "observation_end": d.get("observation_end"),
        "last_updated": d.get("last_updated"),
    }
