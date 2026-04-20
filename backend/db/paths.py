"""Canonical on-disk paths for the local data lake.

The layout is Hive-partitioned so DuckDB can prune at query time:
``data/parquet/ohlcv/symbol=BTC/interval=1h/year=2024/part-000.parquet``
"""
from __future__ import annotations

from pathlib import Path

# Default root. Callers can override per-environment via constructor args.
DEFAULT_DATA_ROOT = Path("data")

_OHLCV_PARTITION_FILE = "part-000.parquet"
_OUTCOME_PARTITION_FILE = "part-000.parquet"


def ohlcv_partition_dir(data_root: Path, symbol: str, interval: str, year: int) -> Path:
    """Directory holding the parquet file for (symbol, interval, year)."""
    return (
        data_root
        / "parquet"
        / "ohlcv"
        / f"symbol={_sanitize(symbol)}"
        / f"interval={interval}"
        / f"year={year}"
    )


def ohlcv_partition_path(data_root: Path, symbol: str, interval: str, year: int) -> Path:
    """Full path to the parquet file for (symbol, interval, year)."""
    return ohlcv_partition_dir(data_root, symbol, interval, year) / _OHLCV_PARTITION_FILE


def outcome_partition_dir(data_root: Path, market_id: str, year: int) -> Path:
    return (
        data_root
        / "parquet"
        / "outcomes"
        / f"market_id={_sanitize(market_id)}"
        / f"year={year}"
    )


def outcome_partition_path(data_root: Path, market_id: str, year: int) -> Path:
    return outcome_partition_dir(data_root, market_id, year) / _OUTCOME_PARTITION_FILE


def ohlcv_glob(data_root: Path) -> str:
    """DuckDB-friendly glob pattern over the OHLCV lake."""
    return str(data_root / "parquet" / "ohlcv" / "**" / "*.parquet")


def outcome_glob(data_root: Path) -> str:
    return str(data_root / "parquet" / "outcomes" / "**" / "*.parquet")


def _sanitize(component: str) -> str:
    """Make a path component safe.

    HIP-3 symbols have ``:`` which is fine on Linux/macOS but problematic
    on Windows. Replace with ``__`` for cross-platform safety.
    """
    return component.replace(":", "__").replace("/", "_")


def unsanitize_symbol(component: str) -> str:
    return component.replace("__", ":")
