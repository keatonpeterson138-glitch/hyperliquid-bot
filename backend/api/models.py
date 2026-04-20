"""/models — trained-model registry + train launcher.

``POST /models/train`` runs a purged k-fold training job synchronously
(streaming progress arrives in Phase 11 polish via the TradeEngine
event bus). Quick trainings — 200 rows, 5 folds, logreg — finish in <1s
locally; long XGBoost trainings block the request for ~seconds to
minutes depending on dataset size.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.ml import (
    ModelRegistry,
    TrainingConfig,
    get_feature_set,
    get_labeler,
    train,
)

router = APIRouter(tags=["models"])


def get_model_registry() -> ModelRegistry:
    raise HTTPException(status_code=503, detail="ModelRegistry not configured")


def get_catalog_models() -> DuckDBCatalog:
    return DuckDBCatalog(DEFAULT_DATA_ROOT)


RegistryDep = Annotated[ModelRegistry, Depends(get_model_registry)]
CatalogDep = Annotated[DuckDBCatalog, Depends(get_catalog_models)]


class ModelOut(BaseModel):
    id: str
    family: str
    version: str
    path: str
    features: list[str]
    label: str
    metrics: dict[str, float]
    config: dict[str, Any]
    promoted_slot_id: str | None = None
    created_at: datetime | None = None


class TrainRequest(BaseModel):
    family: str = "logreg"
    feature_set: str = "core_v1"
    labeler: str = "direction"
    labeler_kwargs: dict[str, Any] = Field(default_factory=dict)
    symbol: str
    interval: str
    from_ts: datetime
    to_ts: datetime
    n_splits: int = 5
    label_horizon: int = 1
    embargo_bars: int = 10
    model_kwargs: dict[str, Any] = Field(default_factory=dict)


class PromoteRequest(BaseModel):
    slot_id: str | None = None


def _to_out(m) -> ModelOut:
    return ModelOut(
        id=m.id, family=m.family, version=m.version, path=m.path,
        features=m.features, label=m.label, metrics=m.metrics, config=m.config,
        promoted_slot_id=m.promoted_slot_id, created_at=m.created_at,
    )


@router.get("/models", response_model=list[ModelOut])
def list_models(registry: RegistryDep, family: str | None = None) -> list[ModelOut]:
    return [_to_out(m) for m in registry.list(family=family)]


@router.get("/models/{model_id}", response_model=ModelOut)
def get_model(model_id: str, registry: RegistryDep) -> ModelOut:
    m = registry.get(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return _to_out(m)


@router.post("/models/train", response_model=ModelOut)
def train_endpoint(req: TrainRequest, registry: RegistryDep, catalog: CatalogDep) -> ModelOut:
    with catalog:
        bars = catalog.query_candles(req.symbol, req.interval, req.from_ts, req.to_ts)
    if bars is None or bars.empty:
        raise HTTPException(status_code=400, detail="no bars in range")
    try:
        fs = get_feature_set(req.feature_set)
        lab = get_labeler(req.labeler)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cfg = TrainingConfig(
        family=req.family,
        feature_set=fs,
        labeler=lab,
        labeler_kwargs=req.labeler_kwargs,
        n_splits=req.n_splits,
        label_horizon=req.label_horizon,
        embargo_bars=req.embargo_bars,
        model_kwargs=req.model_kwargs,
    )
    try:
        result = train(bars, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = registry.save(
        family=req.family,
        model_obj=result.model,
        features=result.features,
        label=result.label,
        metrics=result.metrics,
        config={
            "feature_set": req.feature_set,
            "labeler": req.labeler,
            "labeler_kwargs": req.labeler_kwargs,
            "symbol": req.symbol,
            "interval": req.interval,
            "from_ts": req.from_ts.isoformat(),
            "to_ts": req.to_ts.isoformat(),
            "n_splits": req.n_splits,
            "label_horizon": req.label_horizon,
            "embargo_bars": req.embargo_bars,
            "model_kwargs": req.model_kwargs,
            "n_samples": result.n_samples,
        },
    )
    return _to_out(record)


@router.post("/models/{model_id}/promote", response_model=ModelOut)
def promote(model_id: str, req: PromoteRequest, registry: RegistryDep) -> ModelOut:
    m = registry.promote(model_id, req.slot_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return _to_out(m)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, registry: RegistryDep) -> None:
    m = registry.get(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    registry.delete(model_id)
