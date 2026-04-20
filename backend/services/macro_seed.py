"""MacroSeedService — auto-populate a canonical "macro + crypto majors"
dataset on first launch so the installed app has real historical data
the moment the backend comes up, not just after the user manually hits
Load Historical Data.

Seed targets (only pulled if the lake is empty for that (symbol, interval)):
  * S&P 500 (^GSPC via yfinance) — 20y/1d, 1y/1h
  * Nasdaq Composite (^IXIC)     — 20y/1d, 1y/1h
  * WTI crude (CL=F)             — 20y/1d, 1y/1h
  * Gold (GC=F)                  — 20y/1d, 1y/1h
  * Silver (SI=F)                — 20y/1d, 1y/1h
  * DXY (DX-Y.NYB)               — 20y/1d, 1y/1h
  * US 10Y Treasury yield (^TNX) — 20y/1d
  * BTC/ETH/SOL                  — 10y/1d, 7y/1h, 2y/15m (via HL+Binance+Coinbase)

Runs in a dedicated background thread — startup returns immediately,
the UI polls ``/bootstrap/status`` for a progress bar.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.backfill_service import BackfillService

logger = logging.getLogger(__name__)


@dataclass
class SeedSlice:
    symbol: str
    interval: str
    days: int
    reason: str  # human-readable, shown in the UI ('20y of S&P', etc.)


@dataclass
class SeedProgress:
    total: int = 0
    done: int = 0
    errors: int = 0
    current: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rows_total: int = 0
    errors_detail: list[dict[str, str]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "done": self.done,
            "errors": self.errors,
            "current": self.current,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "rows_total": self.rows_total,
            "errors_detail": list(self.errors_detail)[-10:],
            "running": self.started_at is not None and self.finished_at is None,
        }


# Seed set. (symbol, interval, approx-days, reason).
DEFAULT_SEED: list[SeedSlice] = [
    # Daily macro — ~20 years back, tiny file sizes.
    SeedSlice("^GSPC",    "1d", 20 * 365, "S&P 500 · 20y"),
    SeedSlice("^IXIC",    "1d", 20 * 365, "Nasdaq Composite · 20y"),
    SeedSlice("CL=F",     "1d", 20 * 365, "WTI crude · 20y"),
    SeedSlice("GC=F",     "1d", 20 * 365, "Gold · 20y"),
    SeedSlice("SI=F",     "1d", 20 * 365, "Silver · 20y"),
    SeedSlice("DX-Y.NYB", "1d", 20 * 365, "Dollar index DXY · 20y"),
    SeedSlice("^TNX",     "1d", 20 * 365, "US 10Y yield · 20y"),

    # Hourly macro — last year for intraday context.
    SeedSlice("^GSPC", "1h", 365, "S&P 500 · 1y hourly"),
    SeedSlice("^IXIC", "1h", 365, "Nasdaq · 1y hourly"),
    SeedSlice("CL=F",  "1h", 365, "WTI crude · 1y hourly"),
    SeedSlice("GC=F",  "1h", 365, "Gold · 1y hourly"),
    SeedSlice("SI=F",  "1h", 365, "Silver · 1y hourly"),

    # Crypto majors — deep via source router stitching.
    SeedSlice("BTC", "1d", 10 * 365, "BTC · 10y daily"),
    SeedSlice("ETH", "1d", 10 * 365, "ETH · 10y daily"),
    SeedSlice("SOL", "1d", 5 * 365,  "SOL · 5y daily"),
    SeedSlice("BTC", "1h", 7 * 365,  "BTC · 7y hourly"),
    SeedSlice("ETH", "1h", 7 * 365,  "ETH · 7y hourly"),
    SeedSlice("BTC", "15m", 3 * 365, "BTC · 3y 15m"),
    SeedSlice("ETH", "15m", 3 * 365, "ETH · 3y 15m"),
]


class MacroSeedService:
    def __init__(
        self,
        backfill_service: BackfillService | None,
        *,
        catalog: DuckDBCatalog | None = None,
        slices: list[SeedSlice] | None = None,
    ) -> None:
        self.backfill_service = backfill_service
        self.catalog = catalog or DuckDBCatalog(DEFAULT_DATA_ROOT)
        self.slices = list(slices or DEFAULT_SEED)
        self.progress = SeedProgress()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── lifecycle ─────────────────────────────────────────────────

    def ensure_started(self) -> None:
        """Start the seed in the background if the lake is missing any
        seed slice. Re-entrant — calling twice is a no-op."""
        if self._thread is not None and self._thread.is_alive():
            return
        if self.backfill_service is None:
            logger.info("macro seed skipped — no backfill service wired")
            return

        missing = self._missing_slices()
        if not missing:
            logger.info("macro seed skipped — lake already populated")
            return

        self.progress = SeedProgress(
            total=len(missing),
            started_at=datetime.now(UTC),
        )
        self._thread = threading.Thread(
            target=self._run, args=(missing,), name="macro-seed", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ── reads ─────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return self.progress.snapshot()

    # ── internals ─────────────────────────────────────────────────

    def _missing_slices(self) -> list[SeedSlice]:
        """Only seed slices the lake doesn't already have meaningful data
        for. Threshold: < 20 bars means "empty"."""
        out: list[SeedSlice] = []
        try:
            with self.catalog:
                df = self.catalog.list_catalog()
        except Exception as exc:  # noqa: BLE001
            logger.warning("macro seed catalog probe failed: %s", exc)
            return list(self.slices)
        known: dict[tuple[str, str], int] = {}
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                known[(str(row["symbol"]), str(row["interval"]))] = int(row["bar_count"])
        for slc in self.slices:
            if known.get((slc.symbol, slc.interval), 0) < 20:
                out.append(slc)
        return out

    def _run(self, slices: list[SeedSlice]) -> None:
        logger.info("macro seed starting — %d slices", len(slices))
        end = datetime.now(UTC)
        assert self.backfill_service is not None
        for slc in slices:
            if self._stop.is_set():
                break
            self.progress.current = f"{slc.symbol} {slc.interval} — {slc.reason}"
            start = end - timedelta(days=slc.days)
            try:
                t0 = time.time()
                summary = self.backfill_service.run(
                    slc.symbol, slc.interval, start, end, allow_partial=True,
                )
                self.progress.rows_total += int(summary.rows_written)
                logger.info(
                    "macro seed: %s %s -> %d rows (%.1fs, sources=%s)",
                    slc.symbol, slc.interval, summary.rows_written,
                    time.time() - t0, summary.sources_used,
                )
            except Exception as exc:  # noqa: BLE001
                self.progress.errors += 1
                self.progress.errors_detail.append({
                    "symbol": slc.symbol,
                    "interval": slc.interval,
                    "error": str(exc)[:200],
                })
                logger.warning("macro seed %s %s failed: %s", slc.symbol, slc.interval, exc)
            finally:
                self.progress.done += 1
        self.progress.current = None
        self.progress.finished_at = datetime.now(UTC)
        logger.info(
            "macro seed complete — %d done, %d errors, %d rows written",
            self.progress.done, self.progress.errors, self.progress.rows_total,
        )
