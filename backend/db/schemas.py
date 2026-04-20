"""pyarrow schemas for the Parquet lake.

These are the source of truth for file format. Every writer/reader
normalizes against them so DuckDB sees a uniform set of columns.
"""
from __future__ import annotations

import pyarrow as pa

OHLCV_SCHEMA: pa.Schema = pa.schema(
    [
        ("timestamp", pa.timestamp("ms", tz="UTC")),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
        ("trades", pa.int64()),
        ("source", pa.string()),
        ("ingested_at", pa.timestamp("ms", tz="UTC")),
    ]
)

OUTCOME_TAPE_SCHEMA: pa.Schema = pa.schema(
    [
        ("timestamp", pa.timestamp("ms", tz="UTC")),
        ("price", pa.float64()),
        ("volume", pa.float64()),
        ("implied_prob", pa.float64()),
        ("best_bid", pa.float64()),
        ("best_ask", pa.float64()),
        ("event_id", pa.string()),
        ("source", pa.string()),
        ("ingested_at", pa.timestamp("ms", tz="UTC")),
    ]
)

OHLCV_DEDUPE_KEYS: tuple[str, ...] = ("timestamp", "source")
OUTCOME_DEDUPE_KEYS: tuple[str, ...] = ("timestamp", "source", "event_id")
