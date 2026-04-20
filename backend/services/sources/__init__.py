"""Source adapters — pluggable OHLCV fetchers behind a common Protocol.

Every adapter implements ``DataSource`` so the ``SourceRouter`` can stitch
history across exchanges/providers transparently. See
`internal_docs/PHASE_1_DATA_PLATFORM.md` for the full plan.
"""

from backend.services.sources.base import (
    CANDLE_COLUMNS,
    CandleFrame,
    DataSource,
    empty_candle_frame,
)

__all__ = ["CANDLE_COLUMNS", "CandleFrame", "DataSource", "empty_candle_frame"]
