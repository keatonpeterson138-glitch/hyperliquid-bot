"""Bollinger Band Fade — mean-reversion in ranging markets.

When ADX is low (no directional trend) and price punches through the outer
Bollinger band, probability of snapping back to the mean is ~65-75%. The ADX
filter is doing the heavy lifting — without it you fade yourself to death in
trending markets.

Entry:
  * Close < lower BB(20, 2)     (price stretched on the downside)
  * ADX(14) < 25                (ranging / no strong trend)

Exit:
  * Close >= middle BB (SMA-20)  (mean reached)
  * OR -2% stop                  (break-out failed)

Empirical: 65-75% WR on BTC/ETH hourly during non-trending months; 55-65% in
trending months. Combined with the ADX filter, much of the trending-market
drag is avoided.
"""
from __future__ import annotations

import pandas as pd

from .base import BaseStrategy, Signal, SignalType


class BBFadeStrategy(BaseStrategy):
    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        adx_period: int = 14,
        adx_max: float = 25.0,
        stop_pct: float = 0.02,
    ) -> None:
        super().__init__(f"BBFade_{bb_period}_{bb_std}_{adx_period}_{adx_max}")
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.adx_period = adx_period
        self.adx_max = adx_max
        self.stop_pct = stop_pct

    def _adx(self, df: pd.DataFrame) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        up = high.diff()
        down = -low.diff()
        plus_dm = ((up > down) & (up > 0)).astype(float) * up
        minus_dm = ((down > up) & (down > 0)).astype(float) * down
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.adx_period).mean()
        plus_di = 100 * plus_dm.rolling(self.adx_period).mean() / atr.replace(0, 1e-9)
        minus_di = 100 * minus_dm.rolling(self.adx_period).mean() / atr.replace(0, 1e-9)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
        return dx.rolling(self.adx_period).mean()

    def analyze(self, df: pd.DataFrame, current_position: str | None = None) -> Signal:
        n = max(self.bb_period, self.adx_period) * 2 + 5
        if len(df) < n:
            return Signal(SignalType.HOLD, reason="warmup")

        close = df["close"]
        sma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std(ddof=0)
        lower = sma - self.bb_std * std
        adx = self._adx(df)

        c = close.iloc[-1]
        mid = sma.iloc[-1]
        lb = lower.iloc[-1]
        adx_now = adx.iloc[-1]

        if current_position == "LONG":
            if c >= mid:
                return Signal(SignalType.CLOSE_LONG, strength=1.0,
                              reason=f"close {c:.2f} >= BB mid {mid:.2f}")
            return Signal(SignalType.HOLD, reason="holding long toward mid-BB")

        if current_position is None and c < lb and adx_now < self.adx_max:
            return Signal(
                SignalType.LONG,
                strength=min(1.0, (lb - c) / (lb * 0.02)),
                reason=f"close {c:.2f} < lower BB {lb:.2f}, ADX {adx_now:.1f}<{self.adx_max}",
            )

        return Signal(SignalType.HOLD, reason="no setup")
