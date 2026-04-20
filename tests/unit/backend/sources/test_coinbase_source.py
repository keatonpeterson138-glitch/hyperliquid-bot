"""Unit tests for CoinbaseSource — mocked HTTP only."""
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from backend.services.sources.base import CANDLE_COLUMNS
from backend.services.sources.coinbase_source import (
    BASE_URL,
    CoinbaseSource,
    _to_coinbase_product,
)


def _fake_candle(ts_s: int, close: float) -> list[object]:
    # Coinbase row layout: [time_s, low, high, open, close, volume]
    return [ts_s, close - 2, close + 2, close - 1, close, 1234.5]


def _source(responder) -> CoinbaseSource:
    return CoinbaseSource(http_client=httpx.Client(transport=httpx.MockTransport(responder)))


class TestCoinbaseSource:
    def test_supports_crypto_only_and_known_intervals(self) -> None:
        src = CoinbaseSource(http_client=httpx.Client())
        try:
            assert src.supports("BTC", "1h")
            assert src.supports("ETH", "1d")
            # 4h not supported by Coinbase's granularity list in this adapter.
            assert not src.supports("BTC", "4h")
            assert not src.supports("xyz:TSLA", "1h")
        finally:
            src.close()

    def test_earliest_available(self) -> None:
        src = CoinbaseSource(http_client=httpx.Client())
        try:
            assert src.earliest_available("BTC", "1h") == datetime(2015, 7, 20, tzinfo=UTC)
            assert src.earliest_available("UNKNOWN", "1h") is None
        finally:
            src.close()

    def test_fetch_canonical_frame(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        start_s = int(start.timestamp())
        candles = [_fake_candle(start_s + 3600 * i, 100 + i) for i in range(3)]

        captured_url: list[str] = []

        def responder(request: httpx.Request) -> httpx.Response:
            captured_url.append(str(request.url))
            return httpx.Response(200, json=candles)

        src = _source(responder)
        frame = src.fetch_candles("BTC", "1h", start, datetime(2024, 1, 1, 3, tzinfo=UTC))

        assert list(frame.bars.columns) == CANDLE_COLUMNS
        assert frame.source == "coinbase"
        assert frame.bars["close"].tolist() == [100.0, 101.0, 102.0]
        assert frame.bars["trades"].isna().all()
        assert captured_url[0].startswith(f"{BASE_URL}/BTC-USD/candles")

    def test_empty_response(self) -> None:
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

        src = CoinbaseSource(
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


def test_to_coinbase_product() -> None:
    assert _to_coinbase_product("btc") == "BTC-USD"
    assert _to_coinbase_product("ETH") == "ETH-USD"
