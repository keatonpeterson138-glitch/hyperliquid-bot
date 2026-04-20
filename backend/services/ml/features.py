"""Feature store — deterministic, point-in-time safe feature computation.

Each feature is a function ``compute(bars_df) -> pd.Series`` whose output
is aligned with ``bars_df.index``. All features use only past bars for
bar ``i`` — no forward peeks. This is enforced by convention (shift/rolling)
and by tests that check the last N rows are unaffected by future data.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FeatureFn = Callable[[pd.DataFrame], pd.Series]


@dataclass
class Feature:
    name: str
    fn: FeatureFn
    description: str = ""


@dataclass
class FeatureSet:
    name: str
    features: list[Feature] = field(default_factory=list)

    def compute(self, bars_df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=bars_df.index)
        for f in self.features:
            out[f.name] = f.fn(bars_df)
        return out


# ── Core features ───────────────────────────────────────────────────


def ret_n(df: pd.DataFrame, n: int) -> pd.Series:
    return df["close"].pct_change(n)


def ema(df: pd.DataFrame, n: int) -> pd.Series:
    return df["close"].ewm(span=n, adjust=False).mean()


def ema_ratio(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    f = ema(df, fast)
    s = ema(df, slow)
    return (f - s) / s


def rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def volume_zscore(df: pd.DataFrame, n: int = 20) -> pd.Series:
    mean = df["volume"].rolling(n).mean()
    std = df["volume"].rolling(n).std(ddof=0)
    return (df["volume"] - mean) / std.replace(0, np.nan)


def realised_vol(df: pd.DataFrame, n: int = 20) -> pd.Series:
    return df["close"].pct_change().rolling(n).std(ddof=0) * np.sqrt(n)


CORE_V1 = FeatureSet(
    name="core_v1",
    features=[
        Feature("ret_1",  lambda df: ret_n(df, 1),  "1-bar return"),
        Feature("ret_5",  lambda df: ret_n(df, 5),  "5-bar return"),
        Feature("ret_20", lambda df: ret_n(df, 20), "20-bar return"),
        Feature("ema_ratio_12_26", lambda df: ema_ratio(df, 12, 26), "EMA(12)/EMA(26)-1"),
        Feature("rsi_14", lambda df: rsi(df, 14), "RSI 14"),
        Feature("atr_14", lambda df: atr(df, 14), "ATR 14"),
        Feature("volume_z_20", lambda df: volume_zscore(df, 20), "20-bar volume z-score"),
        Feature("vol_20", lambda df: realised_vol(df, 20), "Realised volatility (20 bars)"),
    ],
)


FEATURE_SETS: dict[str, FeatureSet] = {CORE_V1.name: CORE_V1}


def get_feature_set(name: str) -> FeatureSet:
    fs = FEATURE_SETS.get(name)
    if fs is None:
        raise KeyError(f"Unknown feature set: {name}")
    return fs
