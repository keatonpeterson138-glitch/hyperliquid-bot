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


# ── momentum_v1: ~35 features across returns / momentum / volatility /
# volume / microstructure time. Deliberately broad — feature importance
# in the trainer output tells you which ones actually matter. ──────


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(df, fast) - ema(df, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    # Normalised to price so the feature is scale-free.
    return macd_line / df["close"], signal_line / df["close"], hist / df["close"]


def stochastic_k(df: pd.DataFrame, n: int = 14) -> pd.Series:
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    denom = (high_n - low_n).replace(0, np.nan)
    return 100 * (df["close"] - low_n) / denom


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    denom = (high_n - low_n).replace(0, np.nan)
    return -100 * (high_n - df["close"]) / denom


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(n).mean()
    md = (tp - ma).abs().rolling(n).mean().replace(0, np.nan)
    return (tp - ma) / (0.015 * md)


def roc(df: pd.DataFrame, n: int) -> pd.Series:
    return df["close"].pct_change(n)


def bollinger_width(df: pd.DataFrame, n: int = 20) -> pd.Series:
    ma = df["close"].rolling(n).mean()
    sd = df["close"].rolling(n).std(ddof=0)
    return (2 * sd) / ma.replace(0, np.nan)


def parkinson_vol(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Parkinson high-low volatility estimator — more efficient than close-only."""
    hl = np.log(df["high"] / df["low"])
    return hl.pow(2).rolling(n).mean().pow(0.5) / np.sqrt(4 * np.log(2))


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def obv_slope(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Rolling slope of OBV via simple linear regression over n bars."""
    o = obv(df)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def _slope(window: np.ndarray) -> float:
        y = window
        y_mean = y.mean()
        return float(((x - x_mean) * (y - y_mean)).sum() / x_var) if x_var > 0 else 0.0

    return o.rolling(n).apply(_slope, raw=True) / df["close"]


def vwap_distance(df: pd.DataFrame, n: int = 24) -> pd.Series:
    """Distance (%) from rolling VWAP."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"]
    vwap = (tp * v).rolling(n).sum() / v.rolling(n).sum().replace(0, np.nan)
    return (df["close"] - vwap) / vwap


def high_low_range(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Current close position inside the last-n-bar range, 0..1."""
    lo = df["low"].rolling(n).min()
    hi = df["high"].rolling(n).max()
    rng = (hi - lo).replace(0, np.nan)
    return (df["close"] - lo) / rng


def time_of_day(df: pd.DataFrame) -> pd.Series:
    """Sin(2π·hour/24) — cyclical encoding; works in any TZ as long as
    it's consistent."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return np.sin(2 * np.pi * ts.dt.hour / 24)


def time_of_day_cos(df: pd.DataFrame) -> pd.Series:
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return np.cos(2 * np.pi * ts.dt.hour / 24)


def day_of_week(df: pd.DataFrame) -> pd.Series:
    """Sin encoding; combined with cos below gives a proper cyclical view."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return np.sin(2 * np.pi * ts.dt.dayofweek / 7)


def day_of_week_cos(df: pd.DataFrame) -> pd.Series:
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return np.cos(2 * np.pi * ts.dt.dayofweek / 7)


MOMENTUM_V1 = FeatureSet(
    name="momentum_v1",
    features=[
        # Returns across multiple horizons.
        Feature("ret_1",   lambda df: ret_n(df, 1),   "1-bar return"),
        Feature("ret_5",   lambda df: ret_n(df, 5),   "5-bar return"),
        Feature("ret_15",  lambda df: ret_n(df, 15),  "15-bar return"),
        Feature("ret_60",  lambda df: ret_n(df, 60),  "60-bar return"),
        Feature("ret_240", lambda df: ret_n(df, 240), "240-bar return"),
        # Trend / moving averages.
        Feature("ema_ratio_12_26",  lambda df: ema_ratio(df, 12, 26),  "EMA(12)/EMA(26)-1"),
        Feature("ema_ratio_26_50",  lambda df: ema_ratio(df, 26, 50),  "EMA(26)/EMA(50)-1"),
        Feature("ema_ratio_50_200", lambda df: ema_ratio(df, 50, 200), "EMA(50)/EMA(200)-1 — macro trend"),
        # Classic momentum oscillators.
        Feature("rsi_7",    lambda df: rsi(df, 7),  "RSI 7"),
        Feature("rsi_14",   lambda df: rsi(df, 14), "RSI 14"),
        Feature("rsi_21",   lambda df: rsi(df, 21), "RSI 21"),
        Feature("stoch_k_14", lambda df: stochastic_k(df, 14), "Stochastic K 14"),
        Feature("williams_r_14", lambda df: williams_r(df, 14), "Williams %R 14"),
        Feature("cci_20",   lambda df: cci(df, 20), "CCI 20"),
        Feature("roc_10",   lambda df: roc(df, 10), "Rate of Change 10"),
        Feature("roc_30",   lambda df: roc(df, 30), "Rate of Change 30"),
        # MACD (normalised to price).
        Feature("macd_line", lambda df: macd(df)[0], "MACD line / close"),
        Feature("macd_sig",  lambda df: macd(df)[1], "MACD signal / close"),
        Feature("macd_hist", lambda df: macd(df)[2], "MACD histogram / close"),
        # Volatility.
        Feature("atr_7",    lambda df: atr(df, 7) / df["close"],  "ATR7 / close"),
        Feature("atr_14",   lambda df: atr(df, 14) / df["close"], "ATR14 / close"),
        Feature("atr_30",   lambda df: atr(df, 30) / df["close"], "ATR30 / close"),
        Feature("bb_width_20", lambda df: bollinger_width(df, 20), "Bollinger band width 20"),
        Feature("vol_20",   lambda df: realised_vol(df, 20), "Realised vol 20"),
        Feature("vol_60",   lambda df: realised_vol(df, 60), "Realised vol 60"),
        Feature("parkinson_20", lambda df: parkinson_vol(df, 20), "Parkinson high-low vol 20"),
        # Volume.
        Feature("volume_z_20",  lambda df: volume_zscore(df, 20), "Volume z-score 20"),
        Feature("volume_z_60",  lambda df: volume_zscore(df, 60), "Volume z-score 60"),
        Feature("obv_slope_20", lambda df: obv_slope(df, 20), "OBV slope / close"),
        Feature("vwap_dist_24", lambda df: vwap_distance(df, 24), "Distance from VWAP 24"),
        Feature("vwap_dist_96", lambda df: vwap_distance(df, 96), "Distance from VWAP 96"),
        # Range positioning.
        Feature("hl_pos_20",  lambda df: high_low_range(df, 20),  "Close position in 20-bar range"),
        Feature("hl_pos_100", lambda df: high_low_range(df, 100), "Close position in 100-bar range"),
        # Time cyclicals.
        Feature("hour_sin", time_of_day, "Hour-of-day sine"),
        Feature("hour_cos", time_of_day_cos, "Hour-of-day cosine"),
        Feature("dow_sin",  day_of_week, "Day-of-week sine"),
        Feature("dow_cos",  day_of_week_cos, "Day-of-week cosine"),
    ],
)


FEATURE_SETS: dict[str, FeatureSet] = {
    CORE_V1.name: CORE_V1,
    MOMENTUM_V1.name: MOMENTUM_V1,
}


def get_feature_set(name: str) -> FeatureSet:
    fs = FEATURE_SETS.get(name)
    if fs is None:
        raise KeyError(f"Unknown feature set: {name}")
    return fs
