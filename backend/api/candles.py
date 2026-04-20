"""/candles, /catalog, /backfill routers."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.models.candles import (
    BackfillRequest,
    BackfillResponse,
    Bar,
    CandlesResponse,
    CatalogEntry,
    CatalogResponse,
)
from backend.services.backfill_service import BackfillService
from backend.services.source_router import SourceRouter

router = APIRouter(tags=["candles"])


# ── Dependency hooks (overridable in tests) ────────────────────────────────


def get_catalog() -> DuckDBCatalog:
    """Default catalog — reads from `./data`."""
    return DuckDBCatalog(DEFAULT_DATA_ROOT)


def get_backfill_service() -> BackfillService:
    # Wired in backend/main.py with the real router. Tests override via
    # app.dependency_overrides so no network is hit.
    raise HTTPException(status_code=503, detail="BackfillService not configured")


# ── /candles ───────────────────────────────────────────────────────────────


CatalogDep = Annotated[DuckDBCatalog, Depends(get_catalog)]
BackfillServiceDep = Annotated[BackfillService, Depends(get_backfill_service)]


@router.get("/candles", response_model=CandlesResponse)
def get_candles(
    catalog: CatalogDep,
    symbol: Annotated[str, Query(min_length=1)],
    interval: Annotated[str, Query(pattern="^(1m|5m|15m|1h|4h|1d)$")],
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime | None = None,
    source: str | None = None,
) -> CandlesResponse:
    """Range query over the Parquet lake."""
    end = to or datetime.now(UTC)
    with catalog:
        df = catalog.query_candles(symbol, interval, from_, end, source=source)

    bars = [
        Bar(
            timestamp=_to_dt(row.timestamp),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            trades=None if pd.isna(row.trades) else int(row.trades),
            source=row.source if not pd.isna(row.source) else None,
        )
        for row in df.itertuples(index=False)
    ]

    breakdown: dict[str, int] = {}
    if not df.empty and "source" in df.columns:
        for src_name, group in df.groupby("source"):
            breakdown[str(src_name)] = int(len(group))

    return CandlesResponse(
        symbol=symbol,
        interval=interval,
        bar_count=len(bars),
        source_breakdown=breakdown,
        bars=bars,
    )


# ── /catalog ───────────────────────────────────────────────────────────────


@router.get("/catalog", response_model=CatalogResponse)
def get_catalog_summary(catalog: CatalogDep) -> CatalogResponse:
    """Per-(symbol, interval) summary of the lake: earliest, latest, counts."""
    with catalog:
        df = catalog.list_catalog()

    entries = [
        CatalogEntry(
            symbol=str(row.symbol),
            interval=str(row.interval),
            earliest=_to_dt(row.earliest) if not pd.isna(row.earliest) else None,
            latest=_to_dt(row.latest) if not pd.isna(row.latest) else None,
            bar_count=int(row.bar_count),
            source_count=int(row.source_count),
        )
        for row in df.itertuples(index=False)
    ]
    return CatalogResponse(entries=entries)


# ── /backfill ──────────────────────────────────────────────────────────────


@router.post("/backfill", response_model=BackfillResponse)
def post_backfill(req: BackfillRequest, service: BackfillServiceDep) -> BackfillResponse:
    """Kick off a backfill for (symbol, interval, start, end).

    Synchronous in v1 — connection stays open until work completes.
    Future async-job variant will return 202 with a `job_id`.
    """
    summary = service.run(
        req.symbol,
        req.interval,
        req.start,
        req.end,
        allow_partial=req.allow_partial,
    )
    if summary.errors and not req.allow_partial:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Source errors during backfill",
                "errors": summary.errors,
                "rows_written": summary.rows_written,
                "sources_used": summary.sources_used,
            },
        )
    return BackfillResponse(
        symbol=summary.symbol,
        interval=summary.interval,
        rows_written=summary.rows_written,
        sources_used=summary.sources_used,
        errors=summary.errors,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _to_dt(value) -> datetime:
    """pandas Timestamp → datetime, preserving UTC."""
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value))


def build_default_backfill_service(*, router: SourceRouter | None = None) -> BackfillService:
    """Factory used by backend.main to install the real service dependency."""
    if router is None:
        from backend.tools.backfill import build_default_router

        router = build_default_router()
    return BackfillService(router)
