"""Unit tests for BinanceSource — mocked HTTP only."""
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from backend.services.sources.base import CANDLE_COLUMNS
from backend.services.sources.binance_source import (
    BASE_URL,
    BinanceSource,
    _to_binance_pair,
)


def _fake_kline(open_time_ms: int, close: float) -> list[object]:
    # Binance kline row layout (12 fields).
    return [
        open_time_ms,
        str(close - 1),        # open
        str(close + 2),        # high
        str(close - 2),        # low
        str(close),            # close
        "1234.5",              # volume
        open_time_ms + 60_000, # close_time
        "1234567.8",           # quote_volume
        42,                    # trades
        "500.0",               # taker buy base
        "500000.0",            # taker buy quote
        "0",                   # ignore
    ]


def _source(responder) -> BinanceSource:
    return BinanceSource(http_client=httpx.Client(transport=httpx.MockTransport(responder)))


class TestBinanceSource:
    def test_supports_crypto_only(self) -> None:
        src = BinanceSource(http_client=httpx.Client())
        try:
            assert src.supports("BTC", "1h")
            assert src.supports("ETH", "1d")
            assert not src.supports("xyz:TSLA", "1h")
            assert not src.supports("BTC", "3m")
        finally:
            src.close()

    def test_earliest_available_known_symbol(self) -> None:
        src = BinanceSource(http_client=httpx.Client())
        try:
            assert src.earliest_available("BTC", "1h") == datetime(2017, 8, 17, tzinfo=UTC)
            assert src.earliest_available("UNKNOWN", "1h") is None
        finally:
            src.close()

    def test_fetch_canonical_frame(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        start_ms = int(start.timestamp() * 1000)
        klines = [_fake_kline(start_ms + 3_600_000 * i, 100 + i) for i in range(3)]

        captured_params = {}

        def responder(request: httpx.Request) -> httpx.Response:
            captured_params.update(request.url.params)
            assert str(request.url).startswith(BASE_URL)
            return httpx.Response(200, json=klines)

        src = _source(responder)
        frame = src.fetch_candles(
            "BTC",
            "1h",
            start,
            datetime(2024, 1, 1, 3, tzinfo=UTC),
        )

        assert list(frame.bars.columns) == CANDLE_COLUMNS
        assert len(frame.bars) == 3
        assert frame.source == "binance"
        assert frame.bars["close"].tolist() == [100.0, 101.0, 102.0]
        assert frame.bars["trades"].tolist() == [42, 42, 42]
        assert captured_params["symbol"] == "BTCUSDT"
        assert captured_params["interval"] == "1h"

    def test_empty_response_returns_empty_frame(self) -> None:
        src = _source(lambda req: httpx.Response(200, json=[]))
        frame = src.fetch_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        )
        assert frame.is_empty

    def test_retry_exhausted_returns_empty(self) -> None:
        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        src = BinanceSource(
            http_client=httpx.Client(transport=httpx.MockTransport(responder)),
            retry_attempts=2,
            retry_base_delay_s=0.0,
        )
        frame = src.fetch_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        )
        assert frame.is_empty


def test_to_binance_pair() -> None:
    assert _to_binance_pair("btc") == "BTCUSDT"
    assert _to_binance_pair("ETH") == "ETHUSDT"
