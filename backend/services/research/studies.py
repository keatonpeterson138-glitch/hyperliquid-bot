"""Study protocol + registry.

A Study is a pure function ``run(inputs, candle_query) -> StudyResult``.
Every study returns a DataFrame (primary result) + a dict of chart specs
(vega-lite-lite: {type, x, y, series}) + a markdown summary.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CandleQueryFn = Callable[[str, str, datetime, datetime], pd.DataFrame]


@dataclass
class ChartSpec:
    kind: str                    # 'line' | 'heatmap' | 'bar' | 'scatter'
    title: str
    x: str                       # column name
    y: str | list[str]           # column name(s)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class StudyResult:
    study: str
    inputs: dict[str, Any]
    summary_md: str
    data: pd.DataFrame
    charts: list[ChartSpec] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


class Study(Protocol):
    name: str
    description: str

    def run(self, inputs: dict[str, Any], candle_query: CandleQueryFn) -> StudyResult: ...


class StudyRegistry:
    def __init__(self) -> None:
        self._studies: dict[str, Study] = {}

    def register(self, study: Study) -> None:
        self._studies[study.name] = study

    def get(self, name: str) -> Study | None:
        return self._studies.get(name)

    def list(self) -> list[dict[str, str]]:
        return [{"name": s.name, "description": s.description} for s in self._studies.values()]


# ── Studies ──────────────────────────────────────────────────────────


def _as_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


@dataclass
class CorrelationMatrix:
    name: str = "correlation_matrix"
    description: str = "Pearson close-return correlation across a symbol set."

    def run(self, inputs: dict[str, Any], candle_query: CandleQueryFn) -> StudyResult:
        symbols: list[str] = inputs["symbols"]
        interval: str = inputs["interval"]
        from_ts = _as_dt(inputs["from_ts"])
        to_ts = _as_dt(inputs["to_ts"])

        closes: dict[str, pd.Series] = {}
        for sym in symbols:
            df = candle_query(sym, interval, from_ts, to_ts)
            if df is None or df.empty:
                continue
            df = df.sort_values("timestamp").set_index("timestamp")
            closes[sym] = df["close"].astype(float)

        if len(closes) < 2:
            raise ValueError("correlation_matrix needs ≥ 2 symbols with data")

        frame = pd.DataFrame(closes).sort_index()
        returns = frame.pct_change().dropna(how="all")
        corr = returns.corr()
        summary = (
            f"Correlation over {interval}, "
            f"{from_ts.date()} → {to_ts.date()}, "
            f"{len(returns)} observations."
        )
        return StudyResult(
            study=self.name,
            inputs=inputs,
            summary_md=summary,
            data=corr.reset_index().rename(columns={"index": "symbol"}),
            charts=[ChartSpec(kind="heatmap", title="Correlation", x="symbol", y=list(corr.columns))],
        )


@dataclass
class SeasonalityHeatmap:
    name: str = "seasonality_heatmap"
    description: str = "Average return by day-of-week × hour-of-day."

    def run(self, inputs: dict[str, Any], candle_query: CandleQueryFn) -> StudyResult:
        symbol: str = inputs["symbol"]
        interval: str = inputs["interval"]
        from_ts = _as_dt(inputs["from_ts"])
        to_ts = _as_dt(inputs["to_ts"])
        df = candle_query(symbol, interval, from_ts, to_ts)
        if df is None or df.empty:
            raise ValueError("no data for symbol/interval")
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["return"] = df["close"].pct_change()
        df["dow"] = pd.to_datetime(df["timestamp"]).dt.dayofweek
        df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
        grid = (
            df.dropna(subset=["return"])
            .groupby(["dow", "hour"])["return"]
            .mean()
            .unstack(fill_value=0.0)
        )
        data = grid.reset_index()
        return StudyResult(
            study=self.name,
            inputs=inputs,
            summary_md=f"Average per-bar return by (day-of-week × hour). {len(df)} bars.",
            data=data,
            charts=[ChartSpec(kind="heatmap", title="Seasonality", x="hour", y="dow")],
        )


@dataclass
class VolatilityRegime:
    name: str = "volatility_regime"
    description: str = "Rolling realized volatility with regime buckets."

    def run(self, inputs: dict[str, Any], candle_query: CandleQueryFn) -> StudyResult:
        symbol: str = inputs["symbol"]
        interval: str = inputs["interval"]
        from_ts = _as_dt(inputs["from_ts"])
        to_ts = _as_dt(inputs["to_ts"])
        window: int = int(inputs.get("window", 24))
        df = candle_query(symbol, interval, from_ts, to_ts)
        if df is None or df.empty:
            raise ValueError("no data")
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["return"] = df["close"].pct_change()
        df["vol"] = df["return"].rolling(window).std() * np.sqrt(window)
        # Regime: quintile bucket of current vol vs history
        df["regime_quintile"] = pd.qcut(df["vol"], q=5, labels=False, duplicates="drop")
        summary = (
            f"Rolling vol window={window}; latest vol={df['vol'].iloc[-1]:.4f}, "
            f"regime={int(df['regime_quintile'].iloc[-1]) if pd.notna(df['regime_quintile'].iloc[-1]) else -1}/4."
        )
        return StudyResult(
            study=self.name,
            inputs=inputs,
            summary_md=summary,
            data=df[["timestamp", "return", "vol", "regime_quintile"]].dropna(),
            charts=[ChartSpec(kind="line", title="Rolling Volatility", x="timestamp", y="vol")],
        )


@dataclass
class ReturnsSummary:
    name: str = "returns_summary"
    description: str = "Per-period return distribution stats (mean, std, skew, kurt, quantiles)."

    def run(self, inputs: dict[str, Any], candle_query: CandleQueryFn) -> StudyResult:
        symbol: str = inputs["symbol"]
        interval: str = inputs["interval"]
        from_ts = _as_dt(inputs["from_ts"])
        to_ts = _as_dt(inputs["to_ts"])
        df = candle_query(symbol, interval, from_ts, to_ts)
        if df is None or df.empty:
            raise ValueError("no data")
        df = df.sort_values("timestamp").reset_index(drop=True)
        returns = df["close"].pct_change().dropna()
        stats = {
            "count": float(len(returns)),
            "mean": float(returns.mean()),
            "std": float(returns.std(ddof=0)),
            "skew": float(returns.skew()),
            "kurt": float(returns.kurt()),
            "min": float(returns.min()),
            "p05": float(returns.quantile(0.05)),
            "p50": float(returns.quantile(0.50)),
            "p95": float(returns.quantile(0.95)),
            "max": float(returns.max()),
            "pos_fraction": float((returns > 0).mean()),
        }
        data = pd.DataFrame([stats])
        summary = (
            f"{symbol} {interval}: n={stats['count']:.0f}, μ={stats['mean']:.4%}, "
            f"σ={stats['std']:.4%}, skew={stats['skew']:.2f}, "
            f"kurt={stats['kurt']:.2f}, positive={stats['pos_fraction']:.1%}."
        )
        return StudyResult(
            study=self.name,
            inputs=inputs,
            summary_md=summary,
            data=data,
            charts=[],
        )


@dataclass
class EventStudy:
    name: str = "event_study"
    description: str = "Average return in the N bars surrounding user-supplied event timestamps."

    def run(self, inputs: dict[str, Any], candle_query: CandleQueryFn) -> StudyResult:
        symbol: str = inputs["symbol"]
        interval: str = inputs["interval"]
        from_ts = _as_dt(inputs["from_ts"])
        to_ts = _as_dt(inputs["to_ts"])
        events: list[str] = inputs["events"]
        window = int(inputs.get("window", 12))

        df = candle_query(symbol, interval, from_ts, to_ts)
        if df is None or df.empty:
            raise ValueError("no data")
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["return"] = df["close"].pct_change()
        ts_col = pd.to_datetime(df["timestamp"])

        cohort: list[np.ndarray] = []
        for ev_str in events:
            ev = pd.Timestamp(ev_str)
            # find the bar at or just after ev
            idx = ts_col.searchsorted(ev, side="left")
            if idx < window or idx + window > len(df):
                continue
            seg = df["return"].iloc[idx - window: idx + window].to_numpy()
            cohort.append(seg)
        if not cohort:
            raise ValueError("no valid events in range")
        arr = np.vstack(cohort)
        avg = arr.mean(axis=0)
        cum = np.cumsum(avg)
        offsets = np.arange(-window, window)
        out = pd.DataFrame({"offset_bar": offsets, "avg_return": avg, "cum_return": cum})
        return StudyResult(
            study=self.name,
            inputs=inputs,
            summary_md=f"Event study over {len(cohort)} events, ±{window} bars around each.",
            data=out,
            charts=[ChartSpec(kind="line", title="Average cumulative return around events", x="offset_bar", y="cum_return")],
        )


DEFAULT_REGISTRY: StudyRegistry | None = None


def default_registry() -> StudyRegistry:
    global DEFAULT_REGISTRY
    if DEFAULT_REGISTRY is None:
        reg = StudyRegistry()
        for s in [CorrelationMatrix(), SeasonalityHeatmap(), VolatilityRegime(), ReturnsSummary(), EventStudy()]:
            reg.register(s)
        DEFAULT_REGISTRY = reg
    return DEFAULT_REGISTRY
