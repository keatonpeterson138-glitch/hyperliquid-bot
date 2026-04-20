"""Base types + Protocol for candle-data source adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import pandas as pd

# Canonical column order for every CandleFrame. Adapters fill what they can;
# missing columns are filled with sentinel values by ``empty_candle_frame``.
CANDLE_COLUMNS: list[str] = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trades",
    "source",
    "ingested_at",
]

# Canonical interval strings. Not every source supports every interval.
SUPPORTED_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")


def empty_candle_frame() -> pd.DataFrame:
    """A zero-row DataFrame with the canonical columns and dtypes."""
    return pd.DataFrame(
        {
            "timestamp": pd.Series(dtype="datetime64[ms, UTC]"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
            "trades": pd.Series(dtype="Int64"),  # nullable int
            "source": pd.Series(dtype="string"),
            "ingested_at": pd.Series(dtype="datetime64[ms, UTC]"),
        }
    )


@dataclass(frozen=True)
class CandleFrame:
    """Normalized OHLCV block returned by any DataSource.

    ``bars`` columns match ``CANDLE_COLUMNS`` exactly. Empty frames are
    valid (``bars`` has the right dtypes but zero rows).
    """

    symbol: str
    interval: str
    source: str
    bars: pd.DataFrame
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        missing = [c for c in CANDLE_COLUMNS if c not in self.bars.columns]
        if missing:
            raise ValueError(
                f"CandleFrame bars missing required columns {missing}; "
                f"got {list(self.bars.columns)}"
            )

    @property
    def is_empty(self) -> bool:
        return self.bars.empty

    def earliest_timestamp(self) -> datetime | None:
        if self.is_empty:
            return None
        ts = self.bars["timestamp"].min()
        return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts

    def latest_timestamp(self) -> datetime | None:
        if self.is_empty:
            return None
        ts = self.bars["timestamp"].max()
        return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts


@runtime_checkable
class DataSource(Protocol):
    """Protocol every adapter must satisfy."""

    name: str

    def supports(self, symbol: str, interval: str) -> bool:
        """Fast check — does this source have this symbol/interval at all?"""
        ...

    def earliest_available(self, symbol: str, interval: str) -> datetime | None:
        """Earliest timestamp the source can return. None = unknown."""
        ...

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFrame:
        """Fetch candles in [start, end]. Returns empty frame if nothing found.

        Adapters paginate internally when sources cap response size.
        """
        ...
