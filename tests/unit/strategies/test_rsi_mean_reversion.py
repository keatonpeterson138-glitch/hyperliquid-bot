"""Golden-signal tests for RSIMeanReversionStrategy."""
from __future__ import annotations

from strategies.base import SignalType
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy


class TestRSIMeanReversionStrategy:
    def test_returns_hold_when_data_is_below_lookback_minimum(
        self, rsi_insufficient_ohlcv
    ) -> None:
        strat = RSIMeanReversionStrategy()
        signal = strat.analyze(rsi_insufficient_ohlcv)

        assert signal.signal_type == SignalType.HOLD
        assert "insufficient" in signal.reason.lower()

    def test_emits_long_when_rsi_is_oversold_without_position(
        self, rsi_oversold_ohlcv
    ) -> None:
        strat = RSIMeanReversionStrategy()
        signal = strat.analyze(rsi_oversold_ohlcv, current_position=None)

        assert signal.signal_type == SignalType.LONG
        assert "oversold" in signal.reason.lower()
        assert signal.strength > 0.0

    def test_emits_short_when_rsi_is_overbought_without_position(
        self, rsi_overbought_ohlcv
    ) -> None:
        strat = RSIMeanReversionStrategy()
        signal = strat.analyze(rsi_overbought_ohlcv, current_position=None)

        assert signal.signal_type == SignalType.SHORT
        assert "overbought" in signal.reason.lower()
        assert signal.strength > 0.0

    def test_holds_when_oversold_but_already_long(self, rsi_oversold_ohlcv) -> None:
        strat = RSIMeanReversionStrategy()
        signal = strat.analyze(rsi_oversold_ohlcv, current_position="LONG")

        assert signal.signal_type == SignalType.HOLD

    def test_holds_when_overbought_but_already_short(
        self, rsi_overbought_ohlcv
    ) -> None:
        strat = RSIMeanReversionStrategy()
        signal = strat.analyze(rsi_overbought_ohlcv, current_position="SHORT")

        assert signal.signal_type == SignalType.HOLD

    def test_holds_on_neutral_rsi(self, rsi_neutral_ohlcv) -> None:
        strat = RSIMeanReversionStrategy()
        signal = strat.analyze(rsi_neutral_ohlcv)

        assert signal.signal_type == SignalType.HOLD

    def test_custom_thresholds_narrow_the_trigger_band(
        self, rsi_oversold_ohlcv
    ) -> None:
        # Tighter threshold (20) should still trigger on the extreme-oversold fixture.
        strat = RSIMeanReversionStrategy(oversold=20, overbought=80)
        signal = strat.analyze(rsi_oversold_ohlcv)

        assert signal.signal_type == SignalType.LONG
