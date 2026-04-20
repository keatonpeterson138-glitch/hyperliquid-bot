"""MLStrategy — load a trained model and expose it through the BaseStrategy
contract so ``get_strategy('ml:<model_id>')`` returns something deployable
as a slot.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend.services.ml.features import get_feature_set
from backend.services.ml.registry import ModelRegistry
from strategies.base import BaseStrategy, Signal, SignalType

logger = logging.getLogger(__name__)

DEFAULT_LONG_THRESHOLD = 0.55
DEFAULT_SHORT_THRESHOLD = 0.45


class MLStrategy(BaseStrategy):
    def __init__(
        self,
        model_id: str,
        registry: ModelRegistry,
        *,
        long_threshold: float = DEFAULT_LONG_THRESHOLD,
        short_threshold: float = DEFAULT_SHORT_THRESHOLD,
    ) -> None:
        super().__init__(name=f"ml:{model_id}")
        record = registry.get(model_id)
        if record is None:
            raise ValueError(f"Unknown model: {model_id}")
        self.record = record
        self.model = registry.load_model(record)
        self.feature_set = get_feature_set(record.config.get("feature_set", "core_v1"))
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold

    def analyze(self, df: pd.DataFrame, current_position: str | None = None) -> Signal:
        if df is None or df.empty:
            return Signal(SignalType.HOLD, 0.0, "no data")
        features = self.feature_set.compute(df)
        row = features.iloc[[-1]].dropna(axis=1, how="all")
        if row.isna().any().any():
            return Signal(SignalType.HOLD, 0.0, "features incomplete")
        proba = _predict_proba(self.model, row)[0]

        if proba >= self.long_threshold:
            if current_position == "LONG":
                return Signal(SignalType.HOLD, proba, f"still long p={proba:.3f}")
            return Signal(SignalType.LONG, proba, f"ml long p={proba:.3f}")

        if proba <= self.short_threshold:
            if current_position == "SHORT":
                return Signal(SignalType.HOLD, 1 - proba, f"still short p={proba:.3f}")
            return Signal(SignalType.SHORT, 1 - proba, f"ml short p={proba:.3f}")

        # Close if the model has drifted away from conviction.
        if current_position == "LONG" and proba < 0.5:
            return Signal(SignalType.CLOSE_LONG, 0.5 - proba + 0.01, f"ml flat p={proba:.3f}")
        if current_position == "SHORT" and proba > 0.5:
            return Signal(SignalType.CLOSE_SHORT, proba - 0.5 + 0.01, f"ml flat p={proba:.3f}")

        return Signal(SignalType.HOLD, abs(proba - 0.5) * 2, f"ml hold p={proba:.3f}")


def _predict_proba(model: Any, X: pd.DataFrame) -> Any:
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    if hasattr(model, "decision_function"):
        import numpy as np
        raw = model.decision_function(X)
        return 1.0 / (1.0 + np.exp(-raw))
    raise ValueError("model exposes neither predict_proba nor decision_function")
