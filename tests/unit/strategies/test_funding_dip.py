"""Golden-signal tests for FundingDipStrategy.

Strategy is clock-driven — ``datetime.now(tz=UTC)`` is patched so tests
are deterministic regardless of when the suite runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from strategies.base import SignalType
from strategies.funding_dip import FundingDipStrategy


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Funding dip doesn't read OHLCV — an empty frame is sufficient."""
    return pd.DataFrame()


def _freeze_clock(hour: int, minute: int):
    """Patch datetime.now inside strategies.funding_dip to a fixed UTC moment."""
    fake_now = datetime(2026, 4, 20, hour, minute, 0, tzinfo=timezone.utc)

    def _now(tz=None):
        return fake_now

    patcher = patch("strategies.funding_dip.datetime")
    mock_dt = patcher.start()
    mock_dt.now.side_effect = _now
    return patcher


class TestFundingDipStrategy:
    def test_opens_long_in_final_minute_of_hour(self, empty_df) -> None:
        patcher = _freeze_clock(hour=14, minute=59)
        try:
            strat = FundingDipStrategy(buy_before_mins=1, sell_after_mins=5)
            signal = strat.analyze(empty_df, current_position=None)

            assert signal.signal_type == SignalType.LONG
            assert "funding dip entry" in signal.reason.lower()
        finally:
            patcher.stop()

    def test_closes_long_after_bounce_window(self, empty_df) -> None:
        patcher = _freeze_clock(hour=15, minute=6)
        try:
            strat = FundingDipStrategy(buy_before_mins=1, sell_after_mins=5)
            signal = strat.analyze(empty_df, current_position="LONG")

            assert signal.signal_type == SignalType.CLOSE_LONG
            assert "funding dip exit" in signal.reason.lower()
        finally:
            patcher.stop()

    def test_holds_flat_during_middle_of_hour_with_no_position(self, empty_df) -> None:
        patcher = _freeze_clock(hour=15, minute=30)
        try:
            strat = FundingDipStrategy()
            signal = strat.analyze(empty_df, current_position=None)

            assert signal.signal_type == SignalType.HOLD
            assert "waiting" in signal.reason.lower()
        finally:
            patcher.stop()

    def test_holds_long_before_exit_window_opens(self, empty_df) -> None:
        # minute=2, sell_after_mins=5 — too early to exit
        patcher = _freeze_clock(hour=15, minute=2)
        try:
            strat = FundingDipStrategy(buy_before_mins=1, sell_after_mins=5)
            signal = strat.analyze(empty_df, current_position="LONG")

            assert signal.signal_type == SignalType.HOLD
            assert "holding" in signal.reason.lower()
        finally:
            patcher.stop()

    def test_does_not_reopen_long_inside_entry_window_when_already_long(
        self, empty_df
    ) -> None:
        patcher = _freeze_clock(hour=15, minute=59)
        try:
            strat = FundingDipStrategy()
            signal = strat.analyze(empty_df, current_position="LONG")

            # Inside the entry window but already LONG → stay LONG
            assert signal.signal_type == SignalType.HOLD
        finally:
            patcher.stop()

    def test_buy_before_mins_extends_entry_window(self, empty_df) -> None:
        # With buy_before_mins=3, entry window opens at minute 57
        patcher = _freeze_clock(hour=15, minute=57)
        try:
            strat = FundingDipStrategy(buy_before_mins=3, sell_after_mins=5)
            signal = strat.analyze(empty_df, current_position=None)

            assert signal.signal_type == SignalType.LONG
        finally:
            patcher.stop()
