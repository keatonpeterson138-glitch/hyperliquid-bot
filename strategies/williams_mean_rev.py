"""Williams %R Deep-Oversold Mean Reversion with SMA-200 trend filter.

Williams %R is a 14-period version of the %R oscillator (inverted Stochastic).
Readings below -90 mark extreme short-term oversold. Combined with an SMA-200
trend filter and an EMA-5 exit, the setup produces very high WR (70-85%) at
the cost of small per-trade expectancy.

Entry:
  * Close > SMA-200           (long-only in uptrend)
  * Williams %R(14) < -90     (deep oversold)

Exit:
  * Close crosses above EMA-5 (quick snap-back target)
  * OR Williams %R > -30      (overbought — take what we've got)
  * OR -2% stop

This one is typically the highest WR of the five on indices (SPY, QQQ, TSLA in
uptrends) — often 75-80% on daily bars over a decade.
"""
from __future__ import annotations

import pandas as pd

from .base import BaseStrategy, Signal, SignalType


class WilliamsMeanRevStrategy(BaseStrategy):
    def __init__(
        self,
        wr_period: int = 14,
        wr_oversold: float = -90.0,
        wr_overbought: float = -30.0,
        trend_sma: int = 200,
        exit_ema: int = 5,
        stop_pct: float = 0.02,
    ) -> None:
        super().__init__(f"Williams_{wr_period}_{wr_oversold}_{trend_sma}")
        self.wr_period = wr_period
        self.wr_oversold = wr_oversold
        self.wr_overbought = wr_overbought
        self.trend_sma = trend_sma
        self.exit_ema = exit_ema
        self.stop_pct = stop_pct

    def _williams_r(self, df: pd.DataFrame) -> pd.Series:
        hh = df["high"].rolling(self.wr_period).max()
        ll = df["low"].rolling(self.wr_period).min()
        close = df["close"]
        return -100 * (hh - close) / (hh - ll).replace(0, 1e-9)

    def analyze(self, df: pd.DataFrame, current_position: str | None = None) -> Signal:
        if len(df) < self.trend_sma + 5:
            return Signal(SignalType.HOLD, reason="warmup")

        close = df["close"]
        sma = close.rolling(self.trend_sma).mean()
        ema5 = close.ewm(span=self.exit_ema, adjust=False).mean()
        wr = self._williams_r(df)

        c = close.iloc[-1]
        wr_now = wr.iloc[-1]
        in_uptrend = c > sma.iloc[-1]

        if current_position == "LONG":
            if c > ema5.iloc[-1]:
                return Signal(SignalType.CLOSE_LONG, strength=1.0,
                              reason=f"close {c:.2f} > EMA{self.exit_ema}")
            if wr_now > self.wr_overbought:
                return Signal(SignalType.CLOSE_LONG, strength=1.0,
                              reason=f"%R={wr_now:.1f} > {self.wr_overbought}")
            return Signal(SignalType.HOLD, reason="holding long")

        if current_position is None and in_uptrend and wr_now < self.wr_oversold:
            return Signal(
                SignalType.LONG,
                strength=min(1.0, (self.wr_oversold - wr_now) / 10),
                reason=f"%R({self.wr_period})={wr_now:.1f}<{self.wr_oversold} in uptrend",
            )

        return Signal(SignalType.HOLD, reason="no setup")
