"""Canonical on-disk paths for the local data lake.

The layout is Hive-partitioned so DuckDB can prune at query time:
``data/parquet/ohlcv/symbol=BTC/interval=1h/year=2024/part-000.parquet``

Default data root resolution:
  1. ``HYPERLIQUID_BOT_DATA_ROOT`` env var (if set) — absolute override.
  2. ``./data`` in CWD — dev / source-tree default, preserved so nothing
     in the repo breaks.
  3. Platform-specific user-writable location — for the installed app
     where CWD is the install directory:
        Windows: %LOCALAPPDATA%\\hyperliquid-bot\\data
        macOS:   ~/Library/Application Support/hyperliquid-bot/data
        Linux:   $XDG_DATA_HOME/hyperliquid-bot/data
                 (defaulting to ~/.local/share/hyperliquid-bot/data)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_default_data_root() -> Path:
    env = os.environ.get("HYPERLIQUID_BOT_DATA_ROOT")
    if env:
        return Path(env)

    # Source-tree / dev: prefer ./data if it exists or if we can create it.
    local = Path("data")
    if local.exists() or (Path.cwd() / "requirements.txt").exists():
        return local

    # Installed app — OS-specific user-writable path.
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "hyperliquid-bot" / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "hyperliquid-bot" / "data"
    # Linux / BSD
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "hyperliquid-bot" / "data"


DEFAULT_DATA_ROOT: Path = _resolve_default_data_root()

_OHLCV_PARTITION_FILE = "part-000.parquet"
_OUTCOME_PARTITION_FILE = "part-000.parquet"


def ohlcv_partition_dir(data_root: Path, symbol: str, interval: str, year: int) -> Path:
    return (
        data_root
        / "parquet"
        / "ohlcv"
        / f"symbol={_sanitize(symbol)}"
        / f"interval={interval}"
        / f"year={year}"
    )


def ohlcv_partition_path(data_root: Path, symbol: str, interval: str, year: int) -> Path:
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
    return str(data_root / "parquet" / "ohlcv" / "**" / "*.parquet")


def outcome_glob(data_root: Path) -> str:
    return str(data_root / "parquet" / "outcomes" / "**" / "*.parquet")


def _sanitize(component: str) -> str:
    """Make a symbol safe for both Windows paths and Hive partition keys.

    * ``:`` — HIP-3 namespace separator (xyz:TSLA), not legal on Windows.
    * ``=`` — collides with Hive's ``key=value`` partition syntax; DuckDB
      misparses ``symbol=GC=F`` and refuses the read.
    * ``/`` — directory separator everywhere.
    """
    return (
        component
        .replace(":", "__")
        .replace("=", "--EQ--")
        .replace("/", "_")
    )


def unsanitize_symbol(component: str) -> str:
    return (
        component
        .replace("__", ":")
        .replace("--EQ--", "=")
    )
