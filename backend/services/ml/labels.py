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


LABELERS: dict[str, Labeler] = {
    "forward_return": forward_return_n,
    "direction": direction_n,
    "triple_barrier": triple_barrier,
    "vol_adjusted_return": vol_adjusted_return,
}


def get_labeler(name: str) -> Labeler:
    fn = LABELERS.get(name)
    if fn is None:
        raise KeyError(f"Unknown labeler: {name}")
    return fn
