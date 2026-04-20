"""End-to-end ML pipeline tests: features, labels, purged CV, trainer, strategy."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.db.app_db import AppDB
from backend.services.ml import (
    CORE_V1,
    MLStrategy,
    ModelRegistry,
    PurgedKFold,
    TrainingConfig,
    direction_n,
    forward_return_n,
    get_feature_set,
    get_labeler,
    train,
    triple_barrier,
)


def _trending_bars(n: int, trend: float = 0.1, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    closes = 100 + np.arange(n) * trend + rng.standard_normal(n) * 0.3
    closes = np.clip(closes, 1.0, None)
    return pd.DataFrame({
        "timestamp": ts,
        "open": closes, "high": closes + 0.3, "low": closes - 0.3,
        "close": closes, "volume": rng.integers(100, 500, size=n).astype(float),
    })


# ── Features ───────────────────────────────────────────────────────


def test_feature_set_compute_shape() -> None:
    bars = _trending_bars(100, seed=1)
    X = CORE_V1.compute(bars)
    assert list(X.columns) == [f.name for f in CORE_V1.features]
    assert len(X) == len(bars)


def test_feature_no_forward_peek() -> None:
    """Adding future bars must not change the features at any existing bar."""
    bars = _trending_bars(200, seed=2)
    X_full = CORE_V1.compute(bars)
    X_partial = CORE_V1.compute(bars.iloc[:100])
    # Overlap region should be identical.
    pd.testing.assert_frame_equal(
        X_full.iloc[:100].dropna(), X_partial.dropna(), check_exact=False, atol=1e-10
    )


# ── Labels ─────────────────────────────────────────────────────────


def test_forward_return_last_rows_nan() -> None:
    bars = _trending_bars(50)
    fwd = forward_return_n(bars, n=5)
    assert fwd.iloc[-5:].isna().all()


def test_direction_has_three_values() -> None:
    bars = _trending_bars(100)
    d = direction_n(bars, n=1, threshold=0.0)
    vals = set(d.dropna().unique())
    assert vals <= {-1, 0, 1}


def test_triple_barrier_labels_in_set() -> None:
    bars = _trending_bars(100)
    tb = triple_barrier(bars, pt=0.02, sl=0.02, horizon=10)
    vals = set(tb.dropna().unique())
    assert vals <= {-1.0, 0.0, 1.0}


def test_get_labeler_unknown() -> None:
    with pytest.raises(KeyError):
        get_labeler("nope")


# ── CV ─────────────────────────────────────────────────────────────


def test_purged_kfold_shapes() -> None:
    idx = pd.RangeIndex(100)
    cv = PurgedKFold(n_splits=5, label_horizon=1, embargo_bars=2)
    folds = list(cv.split(idx))
    assert len(folds) == 5
    for train_idx, test_idx in folds:
        # No overlap
        assert set(train_idx).isdisjoint(set(test_idx))
        # Purge gap: train indices below test start must stop short of test_start - label_horizon
        if len(test_idx) > 0 and len(train_idx) > 0:
            test_start = test_idx.min()
            below = train_idx[train_idx < test_start]
            if len(below) > 0:
                assert below.max() < test_start


def test_purged_kfold_embargo() -> None:
    idx = pd.RangeIndex(100)
    cv = PurgedKFold(n_splits=4, label_horizon=0, embargo_bars=5)
    for train_idx, test_idx in cv.split(idx):
        if len(test_idx) > 0 and len(train_idx) > 0:
            test_end = test_idx.max()
            above = train_idx[train_idx > test_end]
            if len(above) > 0:
                assert above.min() >= test_end + 5 + 1  # +1 because test_idx[max]+1 is the first excluded


# ── Trainer + strategy + registry ──────────────────────────────────


def test_train_logreg_on_trend() -> None:
    bars = _trending_bars(500, trend=0.15)
    cfg = TrainingConfig(
        family="logreg",
        feature_set=get_feature_set("core_v1"),
        labeler=direction_n,
        labeler_kwargs={"n": 1, "threshold": 0.0},
        n_splits=4,
        label_horizon=1,
        embargo_bars=5,
    )
    result = train(bars, cfg)
    # Strong trend → model should beat the 50% coin flip on OOS
    assert result.metrics["oos_acc"] > 0.5
    assert result.features == [f.name for f in CORE_V1.features]
    assert result.n_samples > 0


def test_train_rejects_insufficient_data() -> None:
    bars = _trending_bars(30)
    cfg = TrainingConfig(
        family="logreg",
        feature_set=get_feature_set("core_v1"),
        labeler=direction_n,
    )
    with pytest.raises(ValueError):
        train(bars, cfg)


def test_registry_save_and_load_roundtrip(tmp_path) -> None:
    db = AppDB(":memory:")
    registry = ModelRegistry(db, root=tmp_path)

    bars = _trending_bars(300, trend=0.12)
    cfg = TrainingConfig(
        family="logreg",
        feature_set=get_feature_set("core_v1"),
        labeler=direction_n,
        n_splits=3,
    )
    result = train(bars, cfg)

    record = registry.save(
        family="logreg",
        model_obj=result.model,
        features=result.features,
        label=result.label,
        metrics=result.metrics,
        config={"feature_set": "core_v1", "source": "test"},
    )
    assert record.id
    fetched = registry.get(record.id)
    assert fetched is not None
    assert fetched.family == "logreg"
    loaded = registry.load_model(fetched)
    # Loaded model should predict_proba
    X = CORE_V1.compute(bars).dropna()
    proba = loaded.predict_proba(X)
    assert proba.shape == (len(X), 2)
    db.close()


def test_ml_strategy_emits_signal(tmp_path) -> None:
    db = AppDB(":memory:")
    registry = ModelRegistry(db, root=tmp_path)
    bars = _trending_bars(500, trend=0.15)
    cfg = TrainingConfig(
        family="logreg",
        feature_set=get_feature_set("core_v1"),
        labeler=direction_n,
        n_splits=4,
    )
    result = train(bars, cfg)
    record = registry.save(
        family="logreg",
        model_obj=result.model,
        features=result.features,
        label=result.label,
        metrics=result.metrics,
        config={"feature_set": "core_v1"},
    )
    strat = MLStrategy(record.id, registry, long_threshold=0.52, short_threshold=0.48)
    signal = strat.analyze(bars, current_position=None)
    assert signal.signal_type is not None
    db.close()


def test_ml_strategy_unknown_model(tmp_path) -> None:
    db = AppDB(":memory:")
    registry = ModelRegistry(db, root=tmp_path)
    with pytest.raises(ValueError):
        MLStrategy("bogus", registry)
    db.close()
