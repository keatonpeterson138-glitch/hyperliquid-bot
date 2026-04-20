"""HIP-4 outcome tape API: ``GET /outcomes/{market_id}/tape``.

Phase 6 grows this into the full prediction-market workspace (board,
detail, pricing-model edge, live WS). Phase 1 just exposes the tape
reader so UI + research can consume it from day one.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Query

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.models.outcomes import OutcomeTapeResponse, OutcomeTick

router = APIRouter(tags=["outcomes"])


def get_catalog() -> DuckDBCatalog:
    return DuckDBCatalog(DEFAULT_DATA_ROOT)


CatalogDep = Annotated[DuckDBCatalog, Depends(get_catalog)]


@router.get("/outcomes/{market_id}/tape", response_model=OutcomeTapeResponse)
def get_outcome_tape(
    market_id: str,
    catalog: CatalogDep,
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime | None = None,
) -> OutcomeTapeResponse:
    end = to or datetime.now(UTC)
    with catalog:
        df = catalog.query_outcomes(market_id, from_, end)

    ticks = [
        OutcomeTick(
            timestamp=_to_dt(row.timestamp),
            price=float(row.price),
            volume=float(row.volume),
            implied_prob=float(row.implied_prob),
            best_bid=None if pd.isna(row.best_bid) else float(row.best_bid),
            best_ask=None if pd.isna(row.best_ask) else float(row.best_ask),
            event_id=None if pd.isna(row.event_id) else str(row.event_id),
            source=None if pd.isna(row.source) else str(row.source),
        )
        for row in df.itertuples(index=False)
    ]
    return OutcomeTapeResponse(
        market_id=market_id,
        tick_count=len(ticks),
        ticks=ticks,
    )


def _to_dt(value) -> datetime:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value))
