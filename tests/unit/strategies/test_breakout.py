"""Golden-signal tests for BreakoutStrategy."""
from __future__ import annotations

from strategies.base import SignalType
from strategies.breakout import BreakoutStrategy


class TestBreakoutStrategy:
    def test_returns_hold_when_data_is_below_lookback_minimum(
        self, breakout_insufficient_ohlcv
    ) -> None:
        strat = BreakoutStrategy()
        signal = strat.analyze(breakout_insufficient_ohlcv)

        assert signal.signal_type == SignalType.HOLD
        assert "insufficient" in signal.reason.lower()

    def test_emits_long_on_bullish_breakout_without_position(
        self, breakout_bullish_ohlcv
    ) -> None:
        strat = BreakoutStrategy()
        signal = strat.analyze(breakout_bullish_ohlcv, current_position=None)

        assert signal.signal_type == SignalType.LONG
        assert "bullish breakout" in signal.reason.lower()

    def test_emits_short_on_bearish_breakout_without_position(
        self, breakout_bearish_ohlcv
    ) -> None:
        strat = BreakoutStrategy()
        signal = strat.analyze(breakout_bearish_ohlcv, current_position=None)

        assert signal.signal_type == SignalType.SHORT
        assert "bearish breakout" in signal.reason.lower()

    def test_holds_when_bullish_breakout_but_already_long(
        self, breakout_bullish_ohlcv
    ) -> None:
        strat = BreakoutStrategy()
        signal = strat.analyze(breakout_bullish_ohlcv, current_position="LONG")

        assert signal.signal_type == SignalType.HOLD

    def test_holds_when_bearish_breakout_but_already_short(
        self, breakout_bearish_ohlcv
    ) -> None:
        strat = BreakoutStrategy()
        signal = strat.analyze(breakout_bearish_ohlcv, current_position="SHORT")

        assert signal.signal_type == SignalType.HOLD

    def test_holds_on_rangebound_price_with_no_breakout(
        self, breakout_no_break_ohlcv
    ) -> None:
        strat = BreakoutStrategy()
        signal = strat.analyze(breakout_no_break_ohlcv)

        assert signal.signal_type == SignalType.HOLD
        assert "no breakout" in signal.reason.lower()
