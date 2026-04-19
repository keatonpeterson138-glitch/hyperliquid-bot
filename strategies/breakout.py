"""Breakout Strategy."""
import pandas as pd
from typing import Optional
from .base import BaseStrategy, Signal, SignalType


class BreakoutStrategy(BaseStrategy):
    """
    Breakout Strategy based on support/resistance levels.
    
    Generates LONG signal when price breaks above resistance.
    Generates SHORT signal when price breaks below support.
    """
    
    def __init__(self, lookback_period: int = 20, breakout_threshold_pct: float = 0.5):
        super().__init__(f"Breakout_{lookback_period}_{breakout_threshold_pct}")
        self.lookback_period = lookback_period
        self.breakout_threshold_pct = breakout_threshold_pct
    
    def analyze(self, df: pd.DataFrame, current_position: Optional[str] = None) -> Signal:
        """Analyze with breakout logic."""
        if len(df) < self.lookback_period + 5:
            return Signal(SignalType.HOLD, reason="Insufficient data")
        
        df = df.copy()
        
        # Calculate support and resistance from recent data
        lookback_df = df.iloc[-self.lookback_period-1:-1]  # Exclude current candle
        resistance = lookback_df['high'].max()
        support = lookback_df['low'].min()
        
        curr_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        curr_high = df['high'].iloc[-1]
        curr_low = df['low'].iloc[-1]
        
        # Calculate breakout threshold
        breakout_buffer = (resistance - support) * (self.breakout_threshold_pct / 100)
        
        # Detect breakouts
        bullish_breakout = (
            prev_close <= resistance and 
            curr_close > resistance + breakout_buffer
        )
        
        bearish_breakout = (
            prev_close >= support and 
            curr_close < support - breakout_buffer
        )
        
        # Entry signals only – exits are handled by on-chain SL/TP orders
        if bullish_breakout and not current_position:
            strength = min((curr_close - resistance) / resistance * 100, 1.0)
            return Signal(SignalType.LONG, strength, 
                        f"Bullish breakout above {resistance:.2f}")
        
        if bearish_breakout and not current_position:
            strength = min((support - curr_close) / support * 100, 1.0)
            return Signal(SignalType.SHORT, strength, 
                        f"Bearish breakout below {support:.2f}")
        
        return Signal(SignalType.HOLD, 0.0, 
                     f"No breakout (Support: {support:.2f}, Resistance: {resistance:.2f})")
