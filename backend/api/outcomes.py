"""HIP-4 outcome API.

- ``GET /outcomes`` — list active HIP-4 markets (outcome board left rail).
- ``GET /outcomes/{market_id}/tape`` — historical per-market tick tape.
- ``GET /outcomes/{market_id}/edge`` — pricing-model edge snapshot.

Phase 6 grows this into the full prediction-market workspace: live
order-book endpoint + WS streaming + slot deployment.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Protocol

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.universe import get_universe_manager
from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.models.market import Market, UniverseResponse
from backend.models.outcomes import (
    OutcomeEdge,
    OutcomeOrderBook,
    OutcomeOrderBookLevel,
    OutcomeTapeResponse,
    OutcomeTick,
)
from backend.services.universe_manager import UniverseManager
from core.pricing_model import PriceBinaryModel

router = APIRouter(tags=["outcomes"])


def get_catalog() -> DuckDBCatalog:
    return DuckDBCatalog(DEFAULT_DATA_ROOT)


def get_pricing_model() -> PriceBinaryModel:
    """Dependency override hook — production wiring in backend.main."""
    raise HTTPException(status_code=503, detail="PricingModel not configured")


UniverseDep = Annotated[UniverseManager, Depends(get_universe_manager)]
CatalogDep = Annotated[DuckDBCatalog, Depends(get_catalog)]
PricingDep = Annotated[PriceBinaryModel, Depends(get_pricing_model)]


@router.get("/outcomes", response_model=UniverseResponse)
def list_outcome_markets(
    um: UniverseDep,
    subcategory: str | None = None,
    active_only: bool = True,
) -> UniverseResponse:
    """List HIP-4 outcome markets; optional subcategory filter.

    Subcategory keys track the OutcomeClient payload — expected values are
    ``politics``, ``sports``, ``crypto``, ``macro`` and whatever new buckets
    the feed surfaces. Unknown subcategories return an empty list rather
    than an error so the board fails soft.
    """
    markets = um.list_markets(kind="outcome", active_only=active_only)
    if subcategory is not None:
        markets = [m for m in markets if m.get("subcategory") == subcategory]
    return UniverseResponse(markets=[Market(**m) for m in markets])


@router.get("/outcomes/{market_id}/edge", response_model=OutcomeEdge)
def get_outcome_edge(
    market_id: str,
    model: PricingDep,
    default_vol: float = 0.80,
) -> OutcomeEdge:
    """Pricing-model edge snapshot for a single outcome.

    The canonical market id for outcomes is ``outcome:<numeric_id>``. We
    accept either the prefixed form or a bare numeric id for ergonomics.
    """
    outcome_id_str = market_id.removeprefix("outcome:")
    try:
        outcome_id = int(outcome_id_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome market_id: {market_id!r} (expected 'outcome:<int>')",
        ) from None

    result = model.analyse(outcome_id, default_vol=default_vol)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Outcome not found or not price-binary: {market_id}",
        )

    return OutcomeEdge(
        market_id=market_id,
        underlying=result.underlying,
        target_price=result.target_price,
        t_years=result.t_years,
        spot=result.spot,
        vol_used=result.vol_used,
        vol_source=result.vol_source,
        theoretical_prob_yes=result.theory.fair_yes,
        theoretical_prob_no=result.theory.fair_no,
        market_yes=result.market_yes,
        market_no=result.market_no,
        edge_yes=result.edge_yes,
        edge_no=result.edge_no,
        implied_vol=result.implied_vol,
    )


class _OrderBookProvider(Protocol):
    def fetch_orderbook(
        self, market_id: str
    ) -> dict: ...  # {bids: [[price,size]], asks: [[price,size]]}


def get_outcome_orderbook() -> _OrderBookProvider:
    """Dependency stub — real wiring in main.py once OutcomeClient is live."""
    raise HTTPException(status_code=503, detail="OutcomeClient not configured")


OrderBookDep = Annotated[_OrderBookProvider, Depends(get_outcome_orderbook)]


@router.get("/outcomes/{market_id}/orderbook", response_model=OutcomeOrderBook)
def get_outcome_orderbook_endpoint(
    market_id: str,
    provider: OrderBookDep,
) -> OutcomeOrderBook:
    """L2 snapshot. Polled at 500ms by the UI; no WS yet (Phase 6 polish)."""
    try:
        snap = provider.fetch_orderbook(market_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OutcomeOrderBook(
        market_id=market_id,
        bids=[OutcomeOrderBookLevel(price=p, size=s) for p, s in snap.get("bids", [])],
        asks=[OutcomeOrderBookLevel(price=p, size=s) for p, s in snap.get("asks", [])],
        timestamp=snap.get("timestamp") or datetime.now(UTC),
    )


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
