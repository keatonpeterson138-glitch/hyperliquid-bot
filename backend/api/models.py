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
            "feature_importance": result.feature_importance,
            "permutation_importance": result.permutation_importance,
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


# ── Backtest-evaluation ────────────────────────────────────────────


class ModelBacktestRequest(BaseModel):
    from_ts: datetime
    to_ts: datetime
    size_usd: float = 100.0
    leverage: int = 1
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    long_threshold: float = 0.55
    short_threshold: float = 0.45


class ModelBacktestResponse(BaseModel):
    model_id: str
    symbol: str
    interval: str
    metrics: dict[str, float]


@router.post("/models/{model_id}/backtest", response_model=ModelBacktestResponse)
def backtest_model(
    model_id: str,
    req: ModelBacktestRequest,
    registry: RegistryDep,
) -> ModelBacktestResponse:
    """Evaluate the trained model as a live strategy over the given
    range — ties Training Lab output to real P&L metrics (Sharpe, DD,
    win rate) rather than just classification accuracy."""
    m = registry.get(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    from backend.db.duckdb_catalog import DuckDBCatalog
    from backend.db.paths import DEFAULT_DATA_ROOT
    from backend.services.backtest import BacktestConfig, BacktestEngine
    from backend.services.ml import MLStrategy

    symbol = str(m.config.get("symbol", ""))
    interval = str(m.config.get("interval", ""))
    if not symbol or not interval:
        raise HTTPException(status_code=400, detail="Model config missing symbol/interval")

    catalog = DuckDBCatalog(DEFAULT_DATA_ROOT)

    def _candle_query(sym, iv, start, end):
        with catalog:
            return catalog.query_candles(sym, iv, start, end)

    def _factory(name: str, params: dict) -> MLStrategy:  # noqa: ARG001
        return MLStrategy(
            model_id,
            registry,
            long_threshold=req.long_threshold,
            short_threshold=req.short_threshold,
        )

    engine = BacktestEngine(candle_query=_candle_query, strategy_factory=_factory)
    cfg = BacktestConfig(
        symbol=symbol,
        interval=interval,
        strategy=f"ml:{model_id}",
        starting_cash=10_000,
        size_usd=req.size_usd,
        leverage=req.leverage,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        bar_lookback=max(200, int(m.config.get("n_splits", 5)) * 20),
    )
    try:
        result = engine.run(cfg, req.from_ts, req.to_ts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelBacktestResponse(
        model_id=model_id,
        symbol=symbol,
        interval=interval,
        metrics=result.metrics,
    )


# ── Hyperparameter tuning (Optuna) ────────────────────────────────


class ModelTuneRequest(BaseModel):
    family: str = "xgb_cls"
    feature_set: str = "momentum_v1"
    labeler: str = "direction"
    labeler_kwargs: dict[str, Any] = Field(default_factory=dict)
    symbol: str
    interval: str
    from_ts: datetime
    to_ts: datetime
    n_trials: int = 20
    n_splits: int = 4
    embargo_bars: int = 10
    rank_by: str = "oos_auc"


class ModelTuneResponse(BaseModel):
    best_params: dict[str, Any]
    best_score: float
    trials: list[dict[str, Any]]


@router.post("/models/tune", response_model=ModelTuneResponse)
def tune_model(req: ModelTuneRequest, catalog: CatalogDep) -> ModelTuneResponse:
    """Run Optuna bayesian search over the family's param space.
    Returns the best params + per-trial metrics. User then hits
    ``/models/train`` with those params to produce a real registered
    model."""
    try:
        import optuna
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Optuna not installed — add `optuna` to requirements.txt",
        ) from exc

    with catalog:
        bars = catalog.query_candles(req.symbol, req.interval, req.from_ts, req.to_ts)
    if bars is None or bars.empty:
        raise HTTPException(status_code=400, detail="no bars in range")

    try:
        fs = get_feature_set(req.feature_set)
        lab = get_labeler(req.labeler)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    param_space = _PARAM_SPACE.get(req.family)
    if param_space is None:
        raise HTTPException(status_code=400, detail=f"no param space for family: {req.family}")

    trials: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        params = param_space(trial)
        cfg = TrainingConfig(
            family=req.family,
            feature_set=fs,
            labeler=lab,
            labeler_kwargs=req.labeler_kwargs,
            n_splits=req.n_splits,
            embargo_bars=req.embargo_bars,
            model_kwargs=params,
        )
        try:
            result = train(bars, cfg)
        except Exception as exc:  # noqa: BLE001
            trials.append({"params": params, "error": str(exc)})
            return -1.0
        score = float(result.metrics.get(req.rank_by, 0.0))
        trials.append({"params": params, "metrics": result.metrics, "score": score})
        return score

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study.optimize(objective, n_trials=req.n_trials, show_progress_bar=False)

    return ModelTuneResponse(
        best_params=study.best_params,
        best_score=float(study.best_value),
        trials=trials[-req.n_trials:],
    )


# Per-family Optuna search spaces. Reasonable defaults — users can
# always fall back to manual params if these prove too narrow.
_PARAM_SPACE: dict[str, Any] = {
    "xgb_cls": lambda t: {
        "n_estimators": t.suggest_int("n_estimators", 100, 500, step=50),
        "max_depth": t.suggest_int("max_depth", 3, 8),
        "learning_rate": t.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "subsample": t.suggest_float("subsample", 0.7, 1.0),
        "colsample_bytree": t.suggest_float("colsample_bytree", 0.7, 1.0),
    },
    "lgbm_cls": lambda t: {
        "n_estimators": t.suggest_int("n_estimators", 100, 500, step=50),
        "num_leaves": t.suggest_int("num_leaves", 15, 127),
        "learning_rate": t.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "min_child_samples": t.suggest_int("min_child_samples", 5, 100),
    },
    "rf_cls": lambda t: {
        "n_estimators": t.suggest_int("n_estimators", 100, 500, step=50),
        "max_depth": t.suggest_int("max_depth", 5, 30),
        "min_samples_leaf": t.suggest_int("min_samples_leaf", 5, 50),
    },
    "logreg": lambda t: {
        "C": t.suggest_float("C", 1e-3, 1e1, log=True),
    },
}
