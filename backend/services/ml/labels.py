"""Labelers — turn future prices into training targets.

Every labeler aligns output to the bar index and marks lookahead rows as
NaN so cross-validation knows to drop them (or purge them via embargo).
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

Labeler = Callable[..., pd.Series]


def forward_return_n(bars: pd.DataFrame, n: int = 1) -> pd.Series:
    """Return over the next n bars, assigned to the *current* bar.

    The last n rows will be NaN because their label is unknown.
    """
    return bars["close"].shift(-n) / bars["close"] - 1


def direction_n(bars: pd.DataFrame, n: int = 1, threshold: float = 0.0) -> pd.Series:
    """+1 if forward return > threshold, -1 if < -threshold, 0 otherwise."""
    r = forward_return_n(bars, n)
    out = pd.Series(0, index=bars.index, dtype="int64")
    out[r > threshold] = 1
    out[r < -threshold] = -1
    out[r.isna()] = np.nan
    return out


def triple_barrier(
    bars: pd.DataFrame,
    *,
    pt: float,
    sl: float,
    horizon: int,
) -> pd.Series:
    """Prado AFML ch. 3 triple-barrier labeler.

    +1 if price hits ``pt`` (profit target, % above entry) within ``horizon``
    bars, -1 if it hits ``-sl``, 0 if the bar times out. Last ``horizon``
    rows are NaN.
    """
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan)
    for i in range(n - horizon):
        entry = close[i]
        upper = entry * (1 + pt)
        lower = entry * (1 - sl)
        future = close[i + 1: i + 1 + horizon]
        hit_up = np.where(future >= upper)[0]
        hit_down = np.where(future <= lower)[0]
        t_up = hit_up[0] if len(hit_up) else horizon + 1
        t_down = hit_down[0] if len(hit_down) else horizon + 1
        if t_up < t_down:
            out[i] = 1
        elif t_down < t_up:
            out[i] = -1
        else:
            out[i] = 0
    return pd.Series(out, index=bars.index, name=f"triple_barrier_{pt}_{sl}_{horizon}")


def vol_adjusted_return(bars: pd.DataFrame, n: int = 1, vol_window: int = 20) -> pd.Series:
    """Forward-return divided by trailing realised vol — a normalised label."""
    fwd = forward_return_n(bars, n)
    vol = bars["close"].pct_change().rolling(vol_window).std(ddof=0).replace(0, np.nan)
    return fwd / vol


def triple_barrier_atr(
    bars: pd.DataFrame,
    *,
    pt_mult: float = 2.0,
    sl_mult: float = 1.0,
    horizon: int = 24,
    atr_window: int = 14,
) -> pd.Series:
    """Volatility-aware triple barrier (Prado AFML ch. 3).

    Instead of fixed ``pt``/``sl`` percentages, the barriers sit at
    ``pt_mult * ATR(n)`` above and ``sl_mult * ATR(n)`` below the entry,
    scaled to current volatility. A 2% barrier in a calm market becomes
    a 6% barrier in a volatile market — same decision surface.

    +1 profit-target hit first, -1 stop-loss hit first, 0 neither within
    ``horizon`` bars. Last ``horizon`` rows are NaN.
    """
    close = bars["close"].to_numpy(dtype=float)
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan)

    # ATR via the same TR formula as features.atr().
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - np.concatenate(([np.nan], close[:-1]))),
        np.abs(low - np.concatenate(([np.nan], close[:-1]))),
    ])
    atr_series = pd.Series(tr).rolling(atr_window).mean().to_numpy()

    for i in range(n - horizon):
        entry = close[i]
        a = atr_series[i]
        if not np.isfinite(a) or a <= 0 or entry <= 0:
            continue
        upper = entry + pt_mult * a
        lower = entry - sl_mult * a
        future = close[i + 1: i + 1 + horizon]
        hit_up = np.where(future >= upper)[0]
        hit_dn = np.where(future <= lower)[0]
        t_up = hit_up[0] if len(hit_up) else horizon + 1
        t_dn = hit_dn[0] if len(hit_dn) else horizon + 1
        if t_up < t_dn:
            out[i] = 1
        elif t_dn < t_up:
            out[i] = -1
        else:
            out[i] = 0
    return pd.Series(out, index=bars.index, name=f"tb_atr_{pt_mult}_{sl_mult}_{horizon}")


LABELERS: dict[str, Labeler] = {
    "forward_return": forward_return_n,
    "direction": direction_n,
    "triple_barrier": triple_barrier,
    "triple_barrier_atr": triple_barrier_atr,
    "vol_adjusted_return": vol_adjusted_return,
}


def get_labeler(name: str) -> Labeler:
    fn = LABELERS.get(name)
    if fn is None:
        raise KeyError(f"Unknown labeler: {name}")
    return fn
