"""Unit tests for HyperliquidSource.

Uses httpx.MockTransport so no network is required.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pandas as pd
import pytest

from backend.services.sources.base import CANDLE_COLUMNS, CandleFrame
from backend.services.sources.hyperliquid_source import (
    MAINNET_URL,
    TESTNET_URL,
    HyperliquidSource,
    _coin_from_symbol,
    _dex_from_symbol,
    _to_utc_ms,
)


def _fake_candle(ts_ms: int, close: float) -> dict[str, object]:
    return {
        "t": ts_ms,
        "T": ts_ms + 60_000,
        "s": "BTC",
        "i": "1m",
        "o": close - 1,
        "c": close,
        "h": close + 2,
        "l": close - 2,
        "v": 100.5,
        "n": 42,
    }


def _build_source(responder) -> HyperliquidSource:
    client = httpx.Client(transport=httpx.MockTransport(responder))
    return HyperliquidSource(testnet=False, http_client=client)


class TestHyperliquidSource:
    def test_supports_all_canonical_intervals(self) -> None:
        src = HyperliquidSource(http_client=httpx.Client())
        try:
            for interval in ("1m", "5m", "15m", "1h", "4h", "1d"):
                assert src.supports("BTC", interval)
            assert not src.supports("BTC", "3m")
            assert not src.supports("", "1h")
        finally:
            src.close()

    def test_uses_mainnet_url_by_default(self) -> None:
        src = HyperliquidSource(http_client=httpx.Client())
        try:
            assert src.base_url == MAINNET_URL
        finally:
            src.close()

    def test_uses_testnet_url_when_flag_set(self) -> None:
        src = HyperliquidSource(testnet=True, http_client=httpx.Client())
        try:
            assert src.base_url == TESTNET_URL
        finally:
            src.close()

    def test_fetch_empty_when_start_after_end(self) -> None:
        src = _build_source(lambda req: httpx.Response(200, json=[]))
        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 1, 1, tzinfo=UTC)
        frame = src.fetch_candles("BTC", "1h", start, end)
        assert frame.is_empty
        assert list(frame.bars.columns) == CANDLE_COLUMNS

    def test_fetch_returns_canonical_frame(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 1, 3, tzinfo=UTC)
        candles = [_fake_candle(_to_utc_ms(start) + 60_000 * 60 * i, 100 + i) for i in range(3)]

        def responder(request: httpx.Request) -> httpx.Response:
            body = request.read()
            assert b'"candleSnapshot"' in body
            assert b'"coin":"BTC"' in body.replace(b" ", b"")
            return httpx.Response(200, json=candles)

        src = _build_source(responder)
        frame = src.fetch_candles("BTC", "1h", start, end)

        assert not frame.is_empty
        assert list(frame.bars.columns) == CANDLE_COLUMNS
        assert len(frame.bars) == 3
        assert frame.source == "hyperliquid"
        assert frame.symbol == "BTC"
        assert frame.interval == "1h"
        assert frame.bars["close"].tolist() == [100.0, 101.0, 102.0]
        assert frame.bars["trades"].tolist() == [42, 42, 42]

    def test_fetch_dedupes_identical_timestamps_across_pages(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 1, 5, tzinfo=UTC)
        # Pagination continues until a response is empty. Set up two
        # overlapping pages + empty terminator — duplicates must be dropped.
        first_page = [_fake_candle(_to_utc_ms(start) + 60_000 * 60 * i, 100 + i) for i in range(3)]
        second_page = [_fake_candle(_to_utc_ms(start) + 60_000 * 60 * i, 200 + i) for i in range(2, 4)]
        responses = iter([first_page, second_page, []])

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(responses, []))

        src = _build_source(responder)
        frame = src.fetch_candles("BTC", "1h", start, end)
        # 3 + 2 overlapping rows → 4 unique timestamps after dedupe.
        assert len(frame.bars) == 4
        assert frame.bars["timestamp"].is_monotonic_increasing

    def test_fetch_routes_hip3_dex_symbol(self) -> None:
        captured: list[bytes] = []

        def responder(request: httpx.Request) -> httpx.Response:
            captured.append(request.read())
            return httpx.Response(200, json=[_fake_candle(_to_utc_ms(datetime(2024, 1, 1, tzinfo=UTC)), 500)])

        src = _build_source(responder)
        frame = src.fetch_candles(
            "xyz:TSLA",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        )

        assert len(captured) >= 1
        body = captured[0].replace(b" ", b"")
        assert b'"coin":"TSLA"' in body
        assert b'"dex":"xyz"' in body
        assert frame.symbol == "xyz:TSLA"

    def test_retry_on_http_error_then_success(self) -> None:
        attempts = {"n": 0}
        candles = [_fake_candle(_to_utc_ms(datetime(2024, 1, 1, tzinfo=UTC)), 100)]

        def responder(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 2:
                return httpx.Response(503, json={"error": "busy"})
            return httpx.Response(200, json=candles)

        client = httpx.Client(transport=httpx.MockTransport(responder))
        src = HyperliquidSource(http_client=client, retry_attempts=3, retry_base_delay_s=0.0)
        frame = src.fetch_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        )
        assert not frame.is_empty
        assert attempts["n"] == 2

    def test_retry_exhausted_returns_empty(self) -> None:
        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        client = httpx.Client(transport=httpx.MockTransport(responder))
        src = HyperliquidSource(http_client=client, retry_attempts=2, retry_base_delay_s=0.0)
        frame = src.fetch_candles(
            "BTC",
            "1h",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 1, 1, tzinfo=UTC),
        )
        assert frame.is_empty

    def test_unsupported_interval_raises(self) -> None:
        src = HyperliquidSource(http_client=httpx.Client())
        try:
            with pytest.raises(ValueError, match="Unsupported"):
                src.fetch_candles(
                    "BTC",
                    "3m",
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 2, tzinfo=UTC),
                )
        finally:
            src.close()


class TestHelpers:
    @pytest.mark.parametrize(
        "symbol,expected_dex,expected_coin",
        [
            ("BTC", "", "BTC"),
            ("xyz:TSLA", "xyz", "TSLA"),
            ("cash:GOLD", "cash", "GOLD"),
        ],
    )
    def test_symbol_decomposition(self, symbol, expected_dex, expected_coin) -> None:
        assert _dex_from_symbol(symbol) == expected_dex
        assert _coin_from_symbol(symbol) == expected_coin

    def test_to_utc_ms_naive_assumes_utc(self) -> None:
        dt = datetime(2024, 1, 1, 0, 0, 0)
        assert _to_utc_ms(dt) == 1704067200000

    def test_to_utc_ms_aware_converts(self) -> None:
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert _to_utc_ms(dt) == 1704067200000


class TestCandleFrame:
    def test_rejects_missing_columns(self) -> None:
        df = pd.DataFrame({"timestamp": [], "open": []})
        with pytest.raises(ValueError, match="missing required columns"):
            CandleFrame(symbol="BTC", interval="1h", source="test", bars=df)
