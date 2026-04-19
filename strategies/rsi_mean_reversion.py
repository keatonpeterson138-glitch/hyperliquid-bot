"""RSI Mean Reversion Strategy."""
import pandas as pd
from typing import Optional
from .base import BaseStrategy, Signal, SignalType


class RSIMeanReversionStrategy(BaseStrategy):
    """
    RSI Mean Reversion Strategy.
    
    Generates LONG signal when RSI is oversold (< oversold_level).
    Generates SHORT signal when RSI is overbought (> overbought_level).
    """
    
    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        super().__init__(f"RSI_MeanReversion_{period}_{oversold}_{overbought}")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def calculate_rsi(self, df: pd.DataFrame) -> pd.Series:
        """Calculate RSI indicator."""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def analyze(self, df: pd.DataFrame, current_position: Optional[str] = None) -> Signal:
        """Analyze with RSI mean reversion logic."""
        if len(df) < self.period + 10:
            return Signal(SignalType.HOLD, reason="Insufficient data")
        
        df = df.copy()
        df['rsi'] = self.calculate_rsi(df)
        
        rsi_curr = df['rsi'].iloc[-1]
        rsi_prev = df['rsi'].iloc[-2]
        
        # Calculate strength based on how extreme the RSI is
        if rsi_curr < self.oversold:
            strength = (self.oversold - rsi_curr) / self.oversold
            strength = min(strength, 1.0)
        elif rsi_curr > self.overbought:
            strength = (rsi_curr - self.overbought) / (100 - self.overbought)
            strength = min(strength, 1.0)
        else:
            strength = 0.0
        
        # Entry signals only – exits are handled by on-chain SL/TP orders
        if rsi_curr < self.oversold and not current_position:
            return Signal(SignalType.LONG, strength, f"RSI oversold: {rsi_curr:.1f}")
        
        if rsi_curr > self.overbought and not current_position:
            return Signal(SignalType.SHORT, strength, f"RSI overbought: {rsi_curr:.1f}")
        
        return Signal(SignalType.HOLD, 0.0, f"RSI: {rsi_curr:.1f}")
