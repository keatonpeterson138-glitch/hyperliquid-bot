"""EMA Crossover Strategy."""
import pandas as pd
import numpy as np
from typing import Optional
from .base import BaseStrategy, Signal, SignalType


class EMACrossoverStrategy(BaseStrategy):
    """
    EMA Crossover Strategy.
    
    Generates LONG signal when fast EMA crosses above slow EMA.
    Generates SHORT signal when fast EMA crosses below slow EMA.
    """
    
    def __init__(self, fast_period: int = 9, slow_period: int = 21):
        super().__init__(f"EMA_Crossover_{fast_period}_{slow_period}")
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def analyze(self, df: pd.DataFrame, current_position: Optional[str] = None) -> Signal:
        """Analyze with EMA crossover logic."""
        if len(df) < self.slow_period + 10:
            return Signal(SignalType.HOLD, reason="Insufficient data")
        
        # Calculate EMAs
        df = df.copy()
        df['ema_fast'] = df['close'].ewm(span=self.fast_period, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.slow_period, adjust=False).mean()
        
        # Get last two rows to detect crossover
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        fast_curr = curr['ema_fast']
        slow_curr = curr['ema_slow']
        fast_prev = prev['ema_fast']
        slow_prev = prev['ema_slow']
        
        # Detect crossovers
        bullish_cross = fast_prev <= slow_prev and fast_curr > slow_curr
        bearish_cross = fast_prev >= slow_prev and fast_curr < slow_curr
        
        # Calculate signal strength based on separation
        separation_pct = abs(fast_curr - slow_curr) / slow_curr * 100
        strength = min(separation_pct / 2.0, 1.0)  # Max strength at 2% separation
        
        # Entry signals only – exits are handled by on-chain SL/TP orders
        if bullish_cross and not current_position:
            return Signal(SignalType.LONG, strength, "Bullish EMA crossover")
        
        if bearish_cross and not current_position:
            return Signal(SignalType.SHORT, strength, "Bearish EMA crossover")
        
        return Signal(SignalType.HOLD, 0.0, f"No crossover (Fast: {fast_curr:.2f}, Slow: {slow_curr:.2f})")
