"""/candles, /catalog, /backfill routers.

/candles auto-backfills when the lake is empty for the requested range —
the UI gets data on first open without any CLI setup. /candles/refresh
pulls the most recent N hours for a (symbol, interval) and appends so a
polling chart shows live bars.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["candles"])


# ── Dependency hooks (overridable in tests) ────────────────────────────────


def get_catalog() -> DuckDBCatalog:
    return DuckDBCatalog(DEFAULT_DATA_ROOT)


def get_backfill_service() -> BackfillService:
    raise HTTPException(status_code=503, detail="BackfillService not configured")


CatalogDep = Annotated[DuckDBCatalog, Depends(get_catalog)]
BackfillServiceDep = Annotated[BackfillService, Depends(get_backfill_service)]


# Approximate bars-per-interval — used to decide "is this range empty
# enough to auto-fetch?" Compared against what the lake actually returns.
_INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "8h": 480, "12h": 720,
    "1d": 1440, "3d": 4320, "1w": 10080, "1M": 43200,
}


def _expected_bars(interval: str, from_ts: datetime, to_ts: datetime) -> int:
    minutes = _INTERVAL_MINUTES.get(interval)
    if not minutes:
        return 0
    span = (to_ts - from_ts).total_seconds() / 60
    return int(span / minutes)


def _query_bars(
    catalog: DuckDBCatalog,
    symbol: str,
    interval: str,
    from_ts: datetime,
    to_ts: datetime,
    source: str | None,
) -> pd.DataFrame:
    with catalog:
        return catalog.query_candles(symbol, interval, from_ts, to_ts, source=source)


def _df_to_response(df: pd.DataFrame, symbol: str, interval: str) -> CandlesResponse:
    bars = [
        Bar(
            timestamp=_to_dt(row.timestamp),
            open=row.open, high=row.high, low=row.low, close=row.close,
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
        symbol=symbol, interval=interval,
        bar_count=len(bars), source_breakdown=breakdown, bars=bars,
    )


# ── /candles ───────────────────────────────────────────────────────────────


@router.get("/candles", response_model=CandlesResponse)
def get_candles(
    catalog: CatalogDep,
    symbol: Annotated[str, Query(min_length=1)],
    interval: Annotated[str, Query(pattern="^(1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M)$")],
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime | None = None,
    source: str | None = None,
    auto_fetch: bool = True,
) -> CandlesResponse:
    """Range query over the Parquet lake.

    If ``auto_fetch`` is true (default) and the lake has < 20% of the
    expected bar count for the range, synchronously run a backfill, then
    re-query. The first ``/candles`` hit on a fresh install populates
    itself without any CLI step. If no backfill service is wired (tests,
    degraded mode) we just return what's in the lake.
    """
    end = to or datetime.now(UTC)
    df = _query_bars(catalog, symbol, interval, from_, end, source)

    if auto_fetch:
        expected = _expected_bars(interval, from_, end)
        have = len(df)
        if expected > 0 and have < expected * 0.2:
            service = _maybe_get_backfill_service()
            if service is not None:
                try:
                    service.run(symbol, interval, from_, end, allow_partial=True)
                    df = _query_bars(catalog, symbol, interval, from_, end, source)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto-fetch failed for %s/%s: %s", symbol, interval, exc
                    )

    return _df_to_response(df, symbol, interval)


@router.post("/candles/refresh", response_model=CandlesResponse)
def refresh_candles(
    catalog: CatalogDep,
    service: BackfillServiceDep,
    symbol: Annotated[str, Query(min_length=1)],
    interval: Annotated[str, Query(pattern="^(1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M)$")],
    hours: Annotated[int, Query(ge=1, le=720)] = 48,
) -> CandlesResponse:
    """Pull the most recent ``hours`` and return the tail.

    The UI polls this every ~30s while a chart is open so live bars
    append as they print. Only touches the tail of the lake.
    """
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    try:
        service.run(symbol, interval, start, end, allow_partial=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh failed for %s/%s: %s", symbol, interval, exc)
    df = _query_bars(catalog, symbol, interval, start, end, None)
    return _df_to_response(df, symbol, interval)


# ── /catalog ───────────────────────────────────────────────────────────────


@router.get("/catalog", response_model=CatalogResponse)
def get_catalog_summary(catalog: CatalogDep) -> CatalogResponse:
    with catalog:
        df = catalog.list_catalog()
    entries = [
        CatalogEntry(
            symbol=str(row.symbol), interval=str(row.interval),
            earliest=_to_dt(row.earliest) if not pd.isna(row.earliest) else None,
            latest=_to_dt(row.latest) if not pd.isna(row.latest) else None,
            bar_count=int(row.bar_count), source_count=int(row.source_count),
        )
        for row in df.itertuples(index=False)
    ]
    return CatalogResponse(entries=entries)


# ── /backfill ──────────────────────────────────────────────────────────────


@router.post("/backfill", response_model=BackfillResponse)
def post_backfill(req: BackfillRequest, service: BackfillServiceDep) -> BackfillResponse:
    summary = service.run(
        req.symbol, req.interval, req.start, req.end,
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
        symbol=summary.symbol, interval=summary.interval,
        rows_written=summary.rows_written,
        sources_used=summary.sources_used,
        errors=summary.errors,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


_shared_service_ref: BackfillService | None = None


def _maybe_get_backfill_service() -> BackfillService | None:
    """Fetch the live backfill service without raising — used by /candles
    auto-fetch so that tests without a wired service just degrade to the
    pre-auto-fetch behavior (return whatever is in the lake)."""
    return _shared_service_ref


def install_backfill_service(service: BackfillService | None) -> None:
    """Called by backend.main at startup to register the service for the
    optional auto-fetch path. Kept separate from the FastAPI DI so
    ``/candles`` can work when the service isn't configured without a
    503 cascade."""
    global _shared_service_ref
    _shared_service_ref = service


def _to_dt(value) -> datetime:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value))


def build_default_backfill_service(
    *,
    router: SourceRouter | None = None,
    credentials=None,
) -> BackfillService:
    if router is None:
        from backend.tools.backfill import build_default_router

        router = build_default_router(credentials=credentials)
    return BackfillService(router)
