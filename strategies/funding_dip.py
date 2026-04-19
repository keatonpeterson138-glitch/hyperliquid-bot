"""Funding Dip Strategy – time-based buy-the-dip around hourly funding."""
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
from .base import BaseStrategy, Signal, SignalType


class FundingDipStrategy(BaseStrategy):
    """
    Buy the funding-rate dip each hour and sell the recovery.

    Hyperliquid settles funding every hour on the dot (UTC).  When funding
    is deeply negative (shorts pay longs) the price often dips right before
    settlement as market-makers adjust.  This strategy exploits that by:

      1. Opening a LONG *buy_before_mins* minutes before each hour.
      2. Closing the LONG *sell_after_mins* minutes into the next hour,
         capturing the post-funding bounce.

    No technical indicators are used – entry/exit is purely clock-driven.
    A normal SL is still placed for safety in case the dip keeps going.
    """

    def __init__(self, buy_before_mins: int = 1, sell_after_mins: int = 5):
        super().__init__(f"Funding_Dip_{buy_before_mins}m/{sell_after_mins}m")
        self.buy_before_mins = max(1, int(buy_before_mins))
        self.sell_after_mins = max(1, int(sell_after_mins))

    def analyze(self, df: pd.DataFrame,
                current_position: Optional[str] = None) -> Signal:
        """Return LONG near the hour mark, CLOSE_LONG after the bounce window."""

        now = datetime.now(timezone.utc)
        minute = now.minute

        # Entry window: last *buy_before_mins* minutes of the hour
        # e.g. buy_before_mins=1  → enter when minute >= 59
        # e.g. buy_before_mins=2  → enter when minute >= 58
        buy_start = 60 - self.buy_before_mins

        if not current_position and minute >= buy_start:
            return Signal(
                SignalType.LONG, 1.0,
                f"Funding dip entry ({self.buy_before_mins}m before hour, "
                f"UTC {now.strftime('%H:%M')})",
            )

        # Exit window: once past *sell_after_mins* and before the next buy window
        # e.g. sell_after_mins=5  → close when minute in [5 .. buy_start)
        if (current_position == "LONG"
                and self.sell_after_mins <= minute < buy_start):
            return Signal(
                SignalType.CLOSE_LONG, 1.0,
                f"Funding dip exit ({self.sell_after_mins}m after hour, "
                f"UTC {now.strftime('%H:%M')})",
            )

        # Between entry fill and exit window, or idle period – just hold
        hold_reason = (
            "Holding funding-dip position, waiting for exit window"
            if current_position else
            "Waiting for next funding window"
        )
        return Signal(SignalType.HOLD, reason=hold_reason)
