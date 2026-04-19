"""Base strategy class and signal types."""
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass
from typing import Optional
import pandas as pd


class SignalType(Enum):
    """Trading signal types."""
    LONG = "LONG"
    SHORT = "SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Trading signal."""
    signal_type: SignalType
    strength: float = 1.0  # 0.0 to 1.0
    reason: str = ""


class BaseStrategy(ABC):
    """Base class for trading strategies."""
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    def analyze(self, df: pd.DataFrame, current_position: Optional[str] = None) -> Signal:
        """
        Analyze market data and generate trading signal.
        
        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)
            current_position: Current position state ('LONG', 'SHORT', or None)
        
        Returns:
            Signal object
        """
        pass
    
    def __str__(self):
        return f"{self.__class__.__name__}({self.name})"
