"""DataUpdater — incremental tail of new bars into the Parquet lake.

Each ``tick()`` call asks the primary source for any bars newer than
what's already in the lake and appends them. A simple scheduling loop
(see ``PeriodicScheduler``) drives ticks at interval-aligned cadence.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db.parquet_reader import latest_timestamp
from backend.db.parquet_writer import append_ohlcv
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.sources.base import (
    CandleFrame,
    DataSource,
    interval_to_timedelta,
)

logger = logging.getLogger(__name__)

# When no history exists for a (symbol, interval), on first tick we pull
# this much back so there's something for the strategy loop to chew on.
_FIRST_RUN_LOOKBACK = timedelta(days=2)


@dataclass
class DataUpdater:
    """Tail new bars for one (symbol, interval) into the lake."""

    symbol: str
    interval: str
    source: DataSource
    data_root: Path = DEFAULT_DATA_ROOT
    on_new_bars: Callable[[CandleFrame], None] | None = None

    def tick(self, *, now: datetime | None = None) -> int:
        """Fetch + append the most-recent missing bars. Returns rows appended."""
        now = now or datetime.now(UTC)
        latest = latest_timestamp(self.symbol, self.interval, data_root=self.data_root)
        bar_td = interval_to_timedelta(self.interval)

        if latest is None:
            start = now - _FIRST_RUN_LOOKBACK
        else:
            start = latest + bar_td

        if start >= now:
            return 0

        try:
            frame = self.source.fetch_candles(self.symbol, self.interval, start, now)
        except Exception as exc:  # noqa: BLE001 — tail should not kill the loop
            logger.error("DataUpdater fetch failed for %s/%s: %s", self.symbol, self.interval, exc)
            return 0

        if frame.is_empty:
            return 0

        n = append_ohlcv(frame, data_root=self.data_root)
        if self.on_new_bars is not None:
            try:
                self.on_new_bars(frame)
            except Exception as cb_exc:  # noqa: BLE001
                logger.exception("on_new_bars callback raised: %s", cb_exc)
        return n


class PeriodicScheduler:
    """Minimal asyncio-based scheduler — wakes every ``interval`` to call ``tick()``.

    For N updaters, create N scheduler tasks. The TradeEngine service in
    Phase 2 will own lifecycle; for Phase 1 the scheduler is standalone
    and invoked directly from the CLI or dev shell.
    """

    def __init__(self, *, interval: timedelta, fn: Callable[[], int]) -> None:
        self.interval = interval
        self.fn = fn
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                self.fn()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Scheduler tick raised: %s", exc)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.interval.total_seconds())
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
