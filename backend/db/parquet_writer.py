"""Parquet writer with Hive partitioning, dedupe, and atomic writes.

Every write funnels through :func:`append_ohlcv` to keep the lake
format consistent. Existing partitions are read → merged → deduped →
atomically replaced so concurrent reads never see a half-written file.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backend.db.paths import (
    DEFAULT_DATA_ROOT,
    ohlcv_partition_dir,
    ohlcv_partition_path,
    outcome_partition_dir,
    outcome_partition_path,
)
from backend.db.schemas import (
    OHLCV_DEDUPE_KEYS,
    OHLCV_SCHEMA,
    OUTCOME_DEDUPE_KEYS,
    OUTCOME_TAPE_SCHEMA,
)
from backend.services.sources.base import CandleFrame

logger = logging.getLogger(__name__)


def append_ohlcv(frame: CandleFrame, *, data_root: Path | None = None) -> int:
    """Append a CandleFrame to the lake.

    Bars are grouped by UTC year — each group lands in its own partition.
    Within each partition, existing rows are merged with the new ones and
    deduped by ``(timestamp, source)`` keeping the LATEST ``ingested_at``.

    Returns the total number of rows written (post-dedupe).
    """
    if frame.is_empty:
        return 0
    root = data_root or DEFAULT_DATA_ROOT
    bars = frame.bars.copy()
    # Ensure timestamp is datetime for year extraction.
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars["_year"] = bars["timestamp"].dt.year

    total_written = 0
    for year, year_slice in bars.groupby("_year"):
        year_df = year_slice.drop(columns="_year")
        partition = ohlcv_partition_path(root, frame.symbol, frame.interval, int(year))
        combined = _merge_with_existing(year_df, partition, dedupe_keys=OHLCV_DEDUPE_KEYS)
        _atomic_write(combined, partition, OHLCV_SCHEMA)
        total_written += len(combined)
    return total_written


def append_outcomes(
    market_id: str,
    bars: pd.DataFrame,
    *,
    data_root: Path | None = None,
) -> int:
    """Append HIP-4 outcome tape rows. Schema from ``OUTCOME_TAPE_SCHEMA``."""
    if bars is None or bars.empty:
        return 0
    root = data_root or DEFAULT_DATA_ROOT
    bars = bars.copy()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars["_year"] = bars["timestamp"].dt.year

    total_written = 0
    for year, year_slice in bars.groupby("_year"):
        year_df = year_slice.drop(columns="_year")
        partition = outcome_partition_path(root, market_id, int(year))
        combined = _merge_with_existing(year_df, partition, dedupe_keys=OUTCOME_DEDUPE_KEYS)
        _atomic_write(combined, partition, OUTCOME_TAPE_SCHEMA)
        total_written += len(combined)
    return total_written


# ── Internal helpers ───────────────────────────────────────────────────────


def _merge_with_existing(
    new_rows: pd.DataFrame,
    partition_path: Path,
    *,
    dedupe_keys: tuple[str, ...],
) -> pd.DataFrame:
    if partition_path.exists():
        existing = pq.read_table(partition_path).to_pandas()
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows.copy()

    # Dedupe: keep the row with the most recent ``ingested_at``.
    combined = combined.sort_values(list(dedupe_keys) + ["ingested_at"])
    combined = combined.drop_duplicates(subset=list(dedupe_keys), keep="last")
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    return combined


def _atomic_write(df: pd.DataFrame, destination: Path, schema: pa.Schema) -> None:
    """Write ``df`` to ``destination`` via a temp file in the same directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Cast each column to the schema type via pyarrow's schema-aware conversion.
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    tmp_path = destination.with_name(f"{destination.name}.tmp.{uuid.uuid4().hex}")
    try:
        pq.write_table(
            table,
            tmp_path,
            compression="zstd",
            use_dictionary=True,
        )
        os.replace(tmp_path, destination)
    except Exception:
        # Best-effort cleanup of the temp file.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# Convenience re-exports so callers can discover paths without importing from
# the paths module separately.
__all__ = [
    "append_ohlcv",
    "append_outcomes",
    "ohlcv_partition_dir",
    "outcome_partition_dir",
]
