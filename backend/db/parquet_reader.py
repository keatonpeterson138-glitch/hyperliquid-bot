"""Parquet reader — hand-rolled so tests don't depend on DuckDB.

For serious queries, use ``backend/db/query.py`` (DuckDB-backed). This
reader is for small direct partition reads, unit tests, and the
incremental updater (``DataUpdater``) which needs ``latest_timestamp``.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from backend.db.paths import (
    DEFAULT_DATA_ROOT,
    ohlcv_partition_dir,
    ohlcv_partition_path,
)
from backend.db.schemas import OHLCV_SCHEMA

logger = logging.getLogger(__name__)


def read_ohlcv(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    *,
    data_root: Path | None = None,
) -> pd.DataFrame:
    """Read OHLCV bars in ``[start, end]`` spanning relevant year partitions.

    Returns an empty DataFrame (with the canonical schema columns) when no
    partitions exist. Timestamps outside the range are filtered out.
    """
    root = data_root or DEFAULT_DATA_ROOT
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    years = range(start.year, end.year + 1)
    frames: list[pd.DataFrame] = []
    for year in years:
        path = ohlcv_partition_path(root, symbol, interval, year)
        if not path.exists():
            continue
        frames.append(pq.read_table(path).to_pandas())

    if not frames:
        return _empty_ohlcv_df()

    bars = pd.concat(frames, ignore_index=True)
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    mask = (bars["timestamp"] >= pd.Timestamp(start)) & (bars["timestamp"] <= pd.Timestamp(end))
    return bars.loc[mask].sort_values("timestamp").reset_index(drop=True)


def latest_timestamp(
    symbol: str,
    interval: str,
    *,
    data_root: Path | None = None,
) -> datetime | None:
    """Return the newest bar timestamp stored for (symbol, interval), or None."""
    root = data_root or DEFAULT_DATA_ROOT
    parent = root / "parquet" / "ohlcv" / f"symbol={_sanitize(symbol)}" / f"interval={interval}"
    if not parent.exists():
        return None
    # Iterate year dirs in reverse so we short-circuit on the newest.
    latest: datetime | None = None
    for year_dir in sorted(parent.iterdir(), reverse=True):
        if not year_dir.is_dir() or not year_dir.name.startswith("year="):
            continue
        part = year_dir / "part-000.parquet"
        if not part.exists():
            continue
        table = pq.read_table(part, columns=["timestamp"])
        if table.num_rows == 0:
            continue
        max_ts = pd.to_datetime(table["timestamp"].to_pandas(), utc=True).max()
        ts = max_ts.to_pydatetime() if hasattr(max_ts, "to_pydatetime") else max_ts
        if latest is None or ts > latest:
            latest = ts
            # Since we walk newest-first, we can stop once we have one.
            break
    return latest


def partition_exists(
    symbol: str,
    interval: str,
    year: int,
    *,
    data_root: Path | None = None,
) -> bool:
    root = data_root or DEFAULT_DATA_ROOT
    return ohlcv_partition_path(root, symbol, interval, year).exists()


def _empty_ohlcv_df() -> pd.DataFrame:
    cols = [f.name for f in OHLCV_SCHEMA]
    df = pd.DataFrame({c: [] for c in cols})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _sanitize(component: str) -> str:
    return component.replace(":", "__").replace("/", "_")


def _partition_dir(root: Path, symbol: str, interval: str, year: int) -> Path:
    return ohlcv_partition_dir(root, symbol, interval, year)
