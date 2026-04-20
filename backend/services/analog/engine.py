"""AnalogEngine — find historical windows that look like the current one.

v1 ships the DTW path (LB_Keogh-pruned brute force over z-scored windows).
The embedding + FAISS path is deferred past v1.0 because it needs a
trained autoencoder + heavy runtime deps; the API shape leaves room for
a ``mode='embedding'`` switch when that's ready.

Forward-return distribution: after the top-K matches are found, we look
``forward_bars`` into the future from each match and report the median,
25/75, 5/95 quantile cumulative returns so the UI can draw a "what
happened next" fan chart.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CandleQueryFn = Callable[[str, str, datetime, datetime], pd.DataFrame]


@dataclass
class AnalogMatch:
    symbol: str
    start_ts: datetime
    end_ts: datetime
    distance: float
    window_close: list[float]     # z-scored window
    forward_return: float | None = None  # cumulative return over forward_bars


@dataclass
class AnalogResult:
    query_symbol: str
    query_window: list[float]     # z-scored
    window_len: int
    forward_bars: int
    matches: list[AnalogMatch]
    forward_distribution: dict[str, float]  # {p05, p25, p50, p75, p95}


def zscore(x: np.ndarray) -> np.ndarray:
    mean = x.mean()
    std = x.std(ddof=0)
    if std < 1e-12:
        return np.zeros_like(x)
    return (x - mean) / std


def lb_keogh_distance(query: np.ndarray, candidate: np.ndarray, radius: int) -> float:
    """Lower-bound Keogh envelope distance — cheap, used to prune DTW.

    Builds an upper/lower envelope of the query within ``radius`` bars,
    sums squared deviation of candidate points that fall outside the
    envelope.
    """
    assert len(query) == len(candidate)
    n = len(query)
    lb_sum = 0.0
    for i in range(n):
        lo = max(0, i - radius)
        hi = min(n - 1, i + radius)
        upper = query[lo: hi + 1].max()
        lower = query[lo: hi + 1].min()
        c = candidate[i]
        if c > upper:
            lb_sum += (c - upper) ** 2
        elif c < lower:
            lb_sum += (c - lower) ** 2
    return float(np.sqrt(lb_sum))


def dtw_distance(a: np.ndarray, b: np.ndarray, window: int | None = None) -> float:
    """Standard Sakoe-Chiba banded DTW. window=None → full DTW."""
    n, m = len(a), len(b)
    w = window if window is not None else max(n, m)
    inf = np.inf
    d = np.full((n + 1, m + 1), inf)
    d[0, 0] = 0.0
    for i in range(1, n + 1):
        j_start = max(1, i - w)
        j_end = min(m, i + w)
        for j in range(j_start, j_end + 1):
            cost = (a[i - 1] - b[j - 1]) ** 2
            d[i, j] = cost + min(d[i - 1, j], d[i, j - 1], d[i - 1, j - 1])
    return float(np.sqrt(d[n, m]))


@dataclass
class AnalogEngine:
    candle_query: CandleQueryFn
    dtw_band_ratio: float = 0.1        # Sakoe-Chiba band = window_len * ratio

    def query(
        self,
        *,
        symbol: str,
        interval: str,
        from_ts: datetime,
        to_ts: datetime,
        query_end_ts: datetime,
        window_len: int = 40,
        forward_bars: int = 20,
        top_k: int = 20,
        scope_symbols: list[str] | None = None,
    ) -> AnalogResult:
        """Find top_k historical windows similar to the window ending at
        ``query_end_ts``. History is scanned over ``[from_ts, to_ts)``;
        scope is ``[symbol]`` by default or ``scope_symbols`` for a
        universe search."""
        scope = scope_symbols or [symbol]

        # 1. Build the query window — the ``window_len`` closes ending at query_end_ts.
        qdf = self.candle_query(symbol, interval, from_ts, query_end_ts)
        if qdf is None or len(qdf) < window_len:
            raise ValueError(f"query window needs ≥ {window_len} bars, got {0 if qdf is None else len(qdf)}")
        qdf = qdf.sort_values("timestamp").reset_index(drop=True)
        q_closes = qdf["close"].to_numpy(dtype=float)[-window_len:]
        q_z = zscore(q_closes)
        band = max(1, int(window_len * self.dtw_band_ratio))

        # 2. Scan scope history for matches.
        candidates: list[tuple[str, pd.DataFrame, np.ndarray]] = []
        for sym in scope:
            hdf = self.candle_query(sym, interval, from_ts, to_ts)
            if hdf is None or len(hdf) < window_len + forward_bars:
                continue
            hdf = hdf.sort_values("timestamp").reset_index(drop=True)
            closes = hdf["close"].to_numpy(dtype=float)
            candidates.append((sym, hdf, closes))

        if not candidates:
            raise ValueError("no candidate history found")

        matches: list[AnalogMatch] = []
        # LB bound threshold — keep a soft cap so we don't do full DTW on obviously bad candidates.
        lb_cap = np.inf
        kept: list[tuple[float, AnalogMatch]] = []

        for sym, hdf, closes in candidates:
            n = len(closes)
            for start in range(0, n - window_len - forward_bars + 1):
                end = start + window_len
                win = zscore(closes[start:end])
                # Prune via LB_Keogh.
                lb = lb_keogh_distance(q_z, win, band)
                if lb >= lb_cap:
                    continue
                # Full DTW.
                dist = dtw_distance(q_z, win, window=band)
                forward_close = closes[end + forward_bars - 1]
                base = closes[end - 1]
                fwd_return = (forward_close - base) / base if base > 0 else 0.0
                match = AnalogMatch(
                    symbol=sym,
                    start_ts=_to_dt(hdf["timestamp"].iloc[start]),
                    end_ts=_to_dt(hdf["timestamp"].iloc[end - 1]),
                    distance=dist,
                    window_close=win.tolist(),
                    forward_return=float(fwd_return),
                )
                kept.append((dist, match))
                # Maintain a running top_k to push the LB cap down aggressively.
                if len(kept) > top_k * 4:
                    kept.sort(key=lambda pr: pr[0])
                    kept = kept[: top_k * 4]
                    lb_cap = kept[-1][0]

        kept.sort(key=lambda pr: pr[0])
        matches = [m for _, m in kept[:top_k]]

        # 3. Forward-return distribution.
        rets = np.array([m.forward_return for m in matches if m.forward_return is not None])
        dist = {}
        if len(rets) > 0:
            for q, label in [(0.05, "p05"), (0.25, "p25"), (0.5, "p50"), (0.75, "p75"), (0.95, "p95")]:
                dist[label] = float(np.quantile(rets, q))
            dist["mean"] = float(rets.mean())
            dist["n"] = float(len(rets))

        return AnalogResult(
            query_symbol=symbol,
            query_window=q_z.tolist(),
            window_len=window_len,
            forward_bars=forward_bars,
            matches=matches,
            forward_distribution=dist,
        )


def _to_dt(value: Any) -> datetime:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
