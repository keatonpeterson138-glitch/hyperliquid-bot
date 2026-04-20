"""SourceRouter — plans multi-source candle fetches.

Given a (symbol, interval, start, end) request, produces an ordered list
of slices, each tagged with the source responsible for that time range.
Walks sources in priority order (most-trusted-for-recent first) and fills
older gaps from fallback sources.

Also exposes a lightweight cross-validation helper to compare two
sources' close prices on an overlapping window.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from backend.services.sources.base import CandleFrame, DataSource

logger = logging.getLogger(__name__)

# Conservative "very old" floor — used when a source doesn't expose its
# earliest timestamp. In practice: means "assume this source covers the
# entire requested range." Router uses this with the source priority
# order to decide which source "wins" the unknown-floor range.
_UNKNOWN_EARLIEST: datetime = datetime(1990, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SourceSlice:
    source: DataSource
    start: datetime
    end: datetime

    @property
    def source_name(self) -> str:
        return self.source.name


@dataclass(frozen=True)
class ValidationResult:
    symbol: str
    interval: str
    source_a: str
    source_b: str
    overlap_rows: int
    divergence_mean_pct: float
    divergence_max_pct: float
    diverged: bool  # True if max divergence > threshold


class SourceRouter:
    """Route candle requests across multiple sources.

    The constructor accepts sources in **priority order** — the most-trusted
    source for RECENT data comes first. Older history is filled by
    successive fallbacks in order.
    """

    def __init__(self, sources: list[DataSource]) -> None:
        if not sources:
            raise ValueError("SourceRouter needs at least one DataSource")
        self._sources = list(sources)

    @property
    def sources(self) -> list[DataSource]:
        return list(self._sources)

    def supports(self, symbol: str, interval: str) -> bool:
        return any(s.supports(symbol, interval) for s in self._sources)

    def plan(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[SourceSlice]:
        """Return non-overlapping slices that together cover (start, end].

        Slices are returned oldest-first. Sources that can't contribute
        (out of range, or don't support the symbol/interval) are skipped.
        """
        if start >= end:
            return []
        candidates = [s for s in self._sources if s.supports(symbol, interval)]
        if not candidates:
            return []

        slices: list[SourceSlice] = []
        cursor = end  # newest boundary not yet covered

        for src in candidates:
            if cursor <= start:
                break
            earliest = src.earliest_available(symbol, interval) or _UNKNOWN_EARLIEST
            src_start = max(earliest, start)
            if src_start >= cursor:
                continue  # source's coverage doesn't reach the uncovered gap
            slices.append(SourceSlice(source=src, start=src_start, end=cursor))
            cursor = src_start

        return list(reversed(slices))  # oldest-first

    def fetch_all(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[CandleFrame]:
        """Execute the plan — convenience for callers that don't need per-slice progress."""
        frames: list[CandleFrame] = []
        for slice_ in self.plan(symbol, interval, start, end):
            frame = slice_.source.fetch_candles(symbol, interval, slice_.start, slice_.end)
            frames.append(frame)
        return frames

    def cross_validate(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        *,
        source_a: str,
        source_b: str,
        divergence_threshold_pct: float = 1.0,
    ) -> ValidationResult:
        """Compare close prices from two named sources over the same window.

        Useful for catching bad data. Returns an empty-ish result when one
        source can't serve the window.
        """
        a = self._resolve(source_a)
        b = self._resolve(source_b)
        frame_a = a.fetch_candles(symbol, interval, start, end)
        frame_b = b.fetch_candles(symbol, interval, start, end)
        if frame_a.is_empty or frame_b.is_empty:
            return ValidationResult(
                symbol=symbol,
                interval=interval,
                source_a=a.name,
                source_b=b.name,
                overlap_rows=0,
                divergence_mean_pct=0.0,
                divergence_max_pct=0.0,
                diverged=False,
            )
        merged = pd.merge(
            frame_a.bars[["timestamp", "close"]].rename(columns={"close": "close_a"}),
            frame_b.bars[["timestamp", "close"]].rename(columns={"close": "close_b"}),
            on="timestamp",
            how="inner",
        )
        if merged.empty:
            return ValidationResult(
                symbol=symbol,
                interval=interval,
                source_a=a.name,
                source_b=b.name,
                overlap_rows=0,
                divergence_mean_pct=0.0,
                divergence_max_pct=0.0,
                diverged=False,
            )
        pct = (merged["close_a"] - merged["close_b"]).abs() / merged["close_b"].abs() * 100.0
        mean = float(pct.mean())
        maxv = float(pct.max())
        return ValidationResult(
            symbol=symbol,
            interval=interval,
            source_a=a.name,
            source_b=b.name,
            overlap_rows=len(merged),
            divergence_mean_pct=mean,
            divergence_max_pct=maxv,
            diverged=maxv > divergence_threshold_pct,
        )

    def _resolve(self, name: str) -> DataSource:
        for src in self._sources:
            if src.name == name:
                return src
        raise KeyError(f"Unknown source: {name}")
