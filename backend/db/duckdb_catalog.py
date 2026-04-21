"""DuckDB catalog + query layer over the Parquet lake.

DuckDB does hive-partition pruning natively, so even the biggest queries
scan only the partitions that matter for the requested window.

For raw partition I/O (latest_timestamp, read_ohlcv single year) use
``backend/db/parquet_reader``. For aggregate queries, time-range scans,
and multi-symbol joins, use this module.
"""
from __future__ import annotations

import glob as _glob
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from backend.db.paths import DEFAULT_DATA_ROOT, ohlcv_glob, outcome_glob

logger = logging.getLogger(__name__)


class DuckDBCatalog:
    """Read-only view onto the Parquet lake via DuckDB."""

    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root = data_root or DEFAULT_DATA_ROOT
        self._conn: duckdb.DuckDBPyConnection | None = None

    def __enter__(self) -> DuckDBCatalog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            # In-memory — views are re-created per session. No persistent
            # catalog file needed for query-time use.
            self._conn = duckdb.connect(":memory:")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Queries ────────────────────────────────────────────────────────────

    def query_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        *,
        source: str | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV bars in ``[start, end]`` for (symbol, interval).

        If ``source`` is specified, only rows from that source are returned;
        otherwise all sources for the symbol/interval are merged (dedupe on
        (timestamp, source) was already applied at write time).
        """
        if not self._has_ohlcv_files():
            return _empty_like_duckdb_ohlcv()

        conn = self.connect()
        sql = """
            SELECT timestamp, open, high, low, close, volume, trades,
                   source, ingested_at, symbol, interval, year
            FROM read_parquet(?, hive_partitioning = 1)
            WHERE symbol = ?
              AND interval = ?
              AND timestamp BETWEEN ? AND ?
        """
        params: list[Any] = [
            ohlcv_glob(self.data_root),
            _sanitize_symbol(symbol),
            interval,
            pd.Timestamp(_ensure_utc(start)),
            pd.Timestamp(_ensure_utc(end)),
        ]
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY timestamp"
        result = conn.execute(sql, params).fetch_df()
        # Restore the human-readable symbol in the output.
        if not result.empty and "symbol" in result.columns:
            result["symbol"] = symbol
        return result

    def query_outcomes(
        self,
        market_id: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if not self._has_outcome_files():
            return _empty_like_duckdb_outcome()
        conn = self.connect()
        sql = """
            SELECT timestamp, price, volume, implied_prob, best_bid, best_ask,
                   event_id, source, ingested_at, market_id, year
            FROM read_parquet(?, hive_partitioning = 1)
            WHERE market_id = ?
              AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
        """
        params = [
            outcome_glob(self.data_root),
            _sanitize_symbol(market_id),
            pd.Timestamp(_ensure_utc(start)),
            pd.Timestamp(_ensure_utc(end)),
        ]
        return conn.execute(sql, params).fetch_df()

    def list_catalog(self) -> pd.DataFrame:
        """Summary: one row per (symbol, interval) with earliest/latest/bar_count."""
        if not self._has_ohlcv_files():
            return pd.DataFrame(
                {
                    "symbol": pd.Series(dtype="string"),
                    "interval": pd.Series(dtype="string"),
                    "earliest": pd.Series(dtype="datetime64[ms, UTC]"),
                    "latest": pd.Series(dtype="datetime64[ms, UTC]"),
                    "bar_count": pd.Series(dtype="int64"),
                    "source_count": pd.Series(dtype="int64"),
                }
            )
        conn = self.connect()
        sql = """
            SELECT
                symbol,
                interval,
                MIN(timestamp) AS earliest,
                MAX(timestamp) AS latest,
                COUNT(*)       AS bar_count,
                COUNT(DISTINCT source) AS source_count
            FROM read_parquet(?, hive_partitioning = 1)
            GROUP BY symbol, interval
            ORDER BY symbol, interval
        """
        result = conn.execute(sql, [ohlcv_glob(self.data_root)]).fetch_df()
        if not result.empty:
            result["symbol"] = result["symbol"].map(_unsanitize_symbol)
        return result

    # ── Internal ───────────────────────────────────────────────────────────

    def _has_ohlcv_files(self) -> bool:
        return bool(_glob.glob(ohlcv_glob(self.data_root), recursive=True))

    def _has_outcome_files(self) -> bool:
        return bool(_glob.glob(outcome_glob(self.data_root), recursive=True))


# ── Module-level convenience wrappers ──────────────────────────────────────


def query_candles(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    *,
    data_root: Path | None = None,
    source: str | None = None,
) -> pd.DataFrame:
    with DuckDBCatalog(data_root) as catalog:
        return catalog.query_candles(symbol, interval, start, end, source=source)


def list_catalog(*, data_root: Path | None = None) -> pd.DataFrame:
    with DuckDBCatalog(data_root) as catalog:
        return catalog.list_catalog()


# ── Helpers ────────────────────────────────────────────────────────────────


def _sanitize_symbol(symbol: str) -> str:
    # Single source of truth in paths._sanitize — handles ``:``, ``=``, and ``/``.
    from backend.db.paths import _sanitize
    return _sanitize(symbol)


def _unsanitize_symbol(value: Any) -> str:
    if pd.isna(value):
        return value
    from backend.db.paths import unsanitize_symbol
    return unsanitize_symbol(str(value))


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _empty_like_duckdb_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.Series(dtype="datetime64[ms, UTC]"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
            "trades": pd.Series(dtype="Int64"),
            "source": pd.Series(dtype="string"),
            "ingested_at": pd.Series(dtype="datetime64[ms, UTC]"),
            "symbol": pd.Series(dtype="string"),
            "interval": pd.Series(dtype="string"),
            "year": pd.Series(dtype="int64"),
        }
    )


def _empty_like_duckdb_outcome() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.Series(dtype="datetime64[ms, UTC]"),
            "price": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
            "implied_prob": pd.Series(dtype="float64"),
            "best_bid": pd.Series(dtype="float64"),
            "best_ask": pd.Series(dtype="float64"),
            "event_id": pd.Series(dtype="string"),
            "source": pd.Series(dtype="string"),
            "ingested_at": pd.Series(dtype="datetime64[ms, UTC]"),
            "market_id": pd.Series(dtype="string"),
            "year": pd.Series(dtype="int64"),
        }
    )
