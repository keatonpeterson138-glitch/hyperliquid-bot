"""/research — run studies over the data lake."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.research import StudyRegistry, default_registry

router = APIRouter(tags=["research"])


def get_registry() -> StudyRegistry:
    return default_registry()


def get_catalog_research() -> DuckDBCatalog:
    return DuckDBCatalog(DEFAULT_DATA_ROOT)


RegistryDep = Annotated[StudyRegistry, Depends(get_registry)]
CatalogDep = Annotated[DuckDBCatalog, Depends(get_catalog_research)]


class StudyInfo(BaseModel):
    name: str
    description: str


class RunRequest(BaseModel):
    study: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class ChartSpecOut(BaseModel):
    kind: str
    title: str
    x: str
    y: str | list[str]
    meta: dict[str, Any] = Field(default_factory=dict)


class StudyRunResponse(BaseModel):
    study: str
    inputs: dict[str, Any]
    summary_md: str
    columns: list[str]
    rows: list[list[Any]]
    charts: list[ChartSpecOut]
    extras: dict[str, Any] = Field(default_factory=dict)


@router.get("/research", response_model=list[StudyInfo])
def list_studies(registry: RegistryDep) -> list[StudyInfo]:
    return [StudyInfo(**s) for s in registry.list()]


@router.post("/research/run", response_model=StudyRunResponse)
def run_study(
    req: RunRequest,
    registry: RegistryDep,
    catalog: CatalogDep,
) -> StudyRunResponse:
    study = registry.get(req.study)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {req.study}")

    def candle_query(symbol, interval, from_ts, to_ts):
        with catalog:
            return catalog.query_candles(symbol, interval, from_ts, to_ts)

    try:
        result = study.run(req.inputs, candle_query)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing input: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = result.data
    # Serialise timestamps to ISO strings.
    for col in data.columns:
        if data[col].dtype.kind == "M":  # datetime
            data[col] = data[col].astype("int64") // 10**9  # epoch seconds, easy for the UI
    return StudyRunResponse(
        study=result.study,
        inputs=result.inputs,
        summary_md=result.summary_md,
        columns=list(data.columns),
        rows=data.to_numpy().tolist(),
        charts=[
            ChartSpecOut(kind=c.kind, title=c.title, x=c.x, y=c.y, meta=c.meta)
            for c in result.charts
        ],
        extras=result.extras,
    )
