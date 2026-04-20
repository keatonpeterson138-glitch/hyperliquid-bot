"""Golden-signal tests for EMACrossoverStrategy.

Locks the strategy's output shape against known inputs. Any change to the
crossover logic, strength formula, or signal reason text that drifts the
asserted fields will break these tests — which is the point.
"""
from __future__ import annotations

import pytest

from strategies.base import SignalType
from strategies.ema_crossover import EMACrossoverStrategy


class TestEMACrossoverStrategy:
    def test_returns_hold_when_data_is_below_lookback_minimum(
        self, ema_insufficient_ohlcv
    ) -> None:
        strat = EMACrossoverStrategy()
        signal = strat.analyze(ema_insufficient_ohlcv)

        assert signal.signal_type == SignalType.HOLD
        assert "insufficient" in signal.reason.lower()

    def test_emits_long_on_fresh_bullish_cross_without_position(
        self, ema_bullish_cross_ohlcv
    ) -> None:
        strat = EMACrossoverStrategy()
        signal = strat.analyze(ema_bullish_cross_ohlcv, current_position=None)

        assert signal.signal_type == SignalType.LONG
        assert "bullish" in signal.reason.lower()
        assert 0.0 < signal.strength <= 1.0

    def test_emits_short_on_fresh_bearish_cross_without_position(
        self, ema_bearish_cross_ohlcv
    ) -> None:
        strat = EMACrossoverStrategy()
        signal = strat.analyze(ema_bearish_cross_ohlcv, current_position=None)

        assert signal.signal_type == SignalType.SHORT
        assert "bearish" in signal.reason.lower()
        assert 0.0 < signal.strength <= 1.0

    def test_holds_when_bullish_cross_but_already_long(
        self, ema_bullish_cross_ohlcv
    ) -> None:
        strat = EMACrossoverStrategy()
        signal = strat.analyze(ema_bullish_cross_ohlcv, current_position="LONG")

        assert signal.signal_type == SignalType.HOLD

    def test_holds_when_bearish_cross_but_already_short(
        self, ema_bearish_cross_ohlcv
    ) -> None:
        strat = EMACrossoverStrategy()
        signal = strat.analyze(ema_bearish_cross_ohlcv, current_position="SHORT")

        assert signal.signal_type == SignalType.HOLD

    def test_holds_on_flat_price_series(self, ema_no_cross_ohlcv) -> None:
        strat = EMACrossoverStrategy()
        signal = strat.analyze(ema_no_cross_ohlcv)

        assert signal.signal_type == SignalType.HOLD
        assert "no crossover" in signal.reason.lower()

    @pytest.mark.parametrize("fast,slow", [(5, 13), (12, 26), (9, 21)])
    def test_custom_periods_construct_and_run(
        self, fast, slow, ema_bullish_cross_ohlcv
    ) -> None:
        strat = EMACrossoverStrategy(fast_period=fast, slow_period=slow)
        # Need enough data for the custom slow period + 10.
        if len(ema_bullish_cross_ohlcv) >= slow + 10:
            signal = strat.analyze(ema_bullish_cross_ohlcv)
            assert signal.signal_type in (
                SignalType.LONG,
                SignalType.SHORT,
                SignalType.HOLD,
            )
