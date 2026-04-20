"""/analog — pattern search over the data lake."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.analog import AnalogEngine

router = APIRouter(tags=["analog"])


def get_analog_engine() -> AnalogEngine:
    raise HTTPException(status_code=503, detail="AnalogEngine not configured")


EngineDep = Annotated[AnalogEngine, Depends(get_analog_engine)]


class AnalogQueryRequest(BaseModel):
    symbol: str
    interval: str
    from_ts: datetime
    to_ts: datetime
    query_end_ts: datetime
    window_len: int = 40
    forward_bars: int = 20
    top_k: int = 20
    scope_symbols: list[str] | None = None


class AnalogMatchOut(BaseModel):
    symbol: str
    start_ts: datetime
    end_ts: datetime
    distance: float
    forward_return: float | None = None


class AnalogQueryResponse(BaseModel):
    query_symbol: str
    window_len: int
    forward_bars: int
    query_window: list[float]
    matches: list[AnalogMatchOut] = Field(default_factory=list)
    forward_distribution: dict[str, float] = Field(default_factory=dict)


@router.post("/analog/query", response_model=AnalogQueryResponse)
def query(req: AnalogQueryRequest, engine: EngineDep) -> AnalogQueryResponse:
    try:
        result = engine.query(
            symbol=req.symbol,
            interval=req.interval,
            from_ts=req.from_ts,
            to_ts=req.to_ts,
            query_end_ts=req.query_end_ts,
            window_len=req.window_len,
            forward_bars=req.forward_bars,
            top_k=req.top_k,
            scope_symbols=req.scope_symbols,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnalogQueryResponse(
        query_symbol=result.query_symbol,
        window_len=result.window_len,
        forward_bars=result.forward_bars,
        query_window=result.query_window,
        matches=[
            AnalogMatchOut(
                symbol=m.symbol, start_ts=m.start_ts, end_ts=m.end_ts,
                distance=m.distance, forward_return=m.forward_return,
            )
            for m in result.matches
        ],
        forward_distribution=result.forward_distribution,
    )


def _candle_query_factory(catalog: DuckDBCatalog):
    def cq(sym, interval, start, end):
        with catalog:
            return catalog.query_candles(sym, interval, start, end)
    return cq


def build_default_engine() -> AnalogEngine:
    return AnalogEngine(candle_query=_candle_query_factory(DuckDBCatalog(DEFAULT_DATA_ROOT)))
