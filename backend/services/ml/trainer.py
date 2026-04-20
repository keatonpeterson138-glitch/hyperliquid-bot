"""Trainer — runs a purged-kfold training job end-to-end.

Takes bars + feature set + labeler + model family, produces a trained
scikit-learn-compatible estimator and a metrics dict. Supports two
baseline families for v1 (``logreg`` + ``xgb_cls``); adding ``rf_cls``
or LSTM is one dict entry away.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.services.ml.cv import PurgedKFold
from backend.services.ml.features import FeatureSet
from backend.services.ml.labels import Labeler

logger = logging.getLogger(__name__)

ModelFactory = Callable[..., Any]


def _logreg_factory(**kwargs: Any) -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, **kwargs)),
    ])


def _xgb_factory(**kwargs: Any) -> Any:
    import xgboost as xgb  # local import — heavy
    return xgb.XGBClassifier(
        n_estimators=kwargs.pop("n_estimators", 200),
        max_depth=kwargs.pop("max_depth", 5),
        learning_rate=kwargs.pop("learning_rate", 0.05),
        eval_metric="logloss",
        tree_method="hist",
        **kwargs,
    )


MODEL_FACTORIES: dict[str, ModelFactory] = {
    "logreg": _logreg_factory,
    "xgb_cls": _xgb_factory,
}


def _binarise(y: pd.Series) -> pd.Series:
    """Convert ternary direction labels to binary for AUC/logloss metrics."""
    out = y.copy()
    out[out < 0] = 0  # short-or-flat vs long
    return out.astype(int)


@dataclass
class TrainingConfig:
    family: str = "logreg"
    feature_set: FeatureSet | None = None
    labeler: Labeler | None = None
    labeler_kwargs: dict[str, Any] = field(default_factory=dict)
    n_splits: int = 5
    label_horizon: int = 1
    embargo_bars: int = 10
    model_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingResult:
    model: Any                       # fitted estimator
    metrics: dict[str, float]        # OOS aggregated
    per_fold: list[dict[str, float]]
    features: list[str]
    label: str
    n_samples: int


def train(bars: pd.DataFrame, cfg: TrainingConfig) -> TrainingResult:
    if cfg.feature_set is None or cfg.labeler is None:
        raise ValueError("feature_set and labeler are required")
    bars = bars.sort_values("timestamp").reset_index(drop=True)

    # Build features + labels.
    X = cfg.feature_set.compute(bars)
    y_full = cfg.labeler(bars, **cfg.labeler_kwargs)
    y = _binarise(y_full.dropna())
    X = X.loc[y.index].dropna()
    y = y.loc[X.index]
    if len(y) < cfg.n_splits * 10:
        raise ValueError(f"not enough samples after label+feature: {len(y)}")

    factory = MODEL_FACTORIES.get(cfg.family)
    if factory is None:
        raise KeyError(f"Unknown model family: {cfg.family}")

    cv = PurgedKFold(
        n_splits=cfg.n_splits,
        label_horizon=cfg.label_horizon,
        embargo_bars=cfg.embargo_bars,
    )
    per_fold: list[dict[str, float]] = []
    pooled_y: list[np.ndarray] = []
    pooled_proba: list[np.ndarray] = []

    for train_idx, test_idx in cv.split(X.index):
        Xtr, ytr = X.iloc[train_idx], y.iloc[train_idx]
        Xte, yte = X.iloc[test_idx], y.iloc[test_idx]
        if len(np.unique(ytr)) < 2:  # degenerate split — skip
            continue
        model = factory(**cfg.model_kwargs)
        model.fit(Xtr, ytr)
        proba = _predict_proba(model, Xte)
        pred = (proba >= 0.5).astype(int)
        fold_metrics = {
            "acc": float(accuracy_score(yte, pred)),
            "f1": float(f1_score(yte, pred, zero_division=0)),
            "logloss": float(log_loss(yte, np.clip(proba, 1e-6, 1 - 1e-6), labels=[0, 1])),
        }
        if len(np.unique(yte)) == 2:
            fold_metrics["auc"] = float(roc_auc_score(yte, proba))
        per_fold.append(fold_metrics)
        pooled_y.append(yte.to_numpy())
        pooled_proba.append(proba)

    if not per_fold:
        raise ValueError("all folds were degenerate — label imbalance or too few samples")

    # Aggregate OOS.
    y_all = np.concatenate(pooled_y)
    proba_all = np.concatenate(pooled_proba)
    pred_all = (proba_all >= 0.5).astype(int)
    aggregated = {
        "oos_acc": float(accuracy_score(y_all, pred_all)),
        "oos_f1": float(f1_score(y_all, pred_all, zero_division=0)),
        "oos_logloss": float(log_loss(y_all, np.clip(proba_all, 1e-6, 1 - 1e-6), labels=[0, 1])),
    }
    if len(np.unique(y_all)) == 2:
        aggregated["oos_auc"] = float(roc_auc_score(y_all, proba_all))

    # Final fit on all data for deployment.
    final_model = factory(**cfg.model_kwargs)
    final_model.fit(X, y)

    return TrainingResult(
        model=final_model,
        metrics=aggregated,
        per_fold=per_fold,
        features=list(X.columns),
        label=cfg.labeler.__name__,
        n_samples=len(y),
    )


def _predict_proba(model: Any, X: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    if hasattr(model, "decision_function"):
        raw = model.decision_function(X)
        return 1.0 / (1.0 + np.exp(-raw))
    raise ValueError("model exposes neither predict_proba nor decision_function")
