"""BackfillService — thin sync wrapper used by the /backfill endpoint.

Deliberately synchronous for v1 — most backfills finish in seconds to a
few minutes, and the HTTP connection handles long-polling fine. Async
job tracking with WS progress ships in a later phase when the UI starts
surfacing live progress bars.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.db.parquet_writer import append_ohlcv
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.source_router import SourceRouter
from backend.services.sources.base import CandleFrame

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillSummary:
    symbol: str
    interval: str
    rows_written: int
    sources_used: list[str]
    errors: list[dict[str, str]]


class BackfillService:
    def __init__(
        self,
        router: SourceRouter,
        *,
        data_root: Path = DEFAULT_DATA_ROOT,
        append_fn: Callable[[CandleFrame, Path], int] | None = None,
    ) -> None:
        self.router = router
        self.data_root = data_root
        self._append = append_fn or (lambda frame, root: append_ohlcv(frame, data_root=root))

    def run(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime | None = None,
        *,
        allow_partial: bool = False,
    ) -> BackfillSummary:
        end = end or datetime.now(UTC)
        plan = self.router.plan(symbol, interval, start, end)
        total = 0
        sources_used: list[str] = []
        errors: list[dict[str, str]] = []

        for slice_ in plan:
            try:
                frame = slice_.source.fetch_candles(symbol, interval, slice_.start, slice_.end)
            except Exception as exc:  # noqa: BLE001
                errors.append({"source": slice_.source_name, "error": str(exc)})
                continue
            if frame.is_empty:
                continue
            n = self._append(frame, self.data_root)
            total += n
            if slice_.source_name not in sources_used:
                sources_used.append(slice_.source_name)

        if errors and not allow_partial:
            logger.warning(
                "Backfill for %s/%s finished with %d errors; reporting partial",
                symbol,
                interval,
                len(errors),
            )

        return BackfillSummary(
            symbol=symbol,
            interval=interval,
            rows_written=total,
            sources_used=sources_used,
            errors=errors,
        )
