"""Market data module for fetching OHLCV data."""
import logging
import pandas as pd
from typing import List, Dict
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MarketData:
    """Fetch and manage market data."""
    
    # Interval mapping to seconds
    INTERVAL_SECONDS = {
        '1m': 60,
        '5m': 300,
        '15m': 900,
        '1h': 3600,
        '4h': 14400,
        '1d': 86400,
    }
    
    def __init__(self, testnet: bool = True, dex: str = ""):
        """Initialize market data fetcher.
        
        Args:
            testnet: Use testnet if True
            dex: HIP-3 dex name ('' for native perps, 'cash' for commodities/stocks)
        """
        self.testnet = testnet
        self.dex = dex
        # Hyperliquid uses their Info API for historical data
        self.base_url = "https://api.hyperliquid-testnet.xyz/info" if testnet else "https://api.hyperliquid.xyz/info"
    
    def fetch_candles(
        self,
        symbol: str,
        interval: str = '15m',
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle data.
        
        Args:
            symbol: Trading symbol (e.g., 'ETH')
            interval: Candle interval ('1m', '5m', '15m', '1h', '4h', '1d')
            limit: Number of candles to fetch
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            # Convert interval to Hyperliquid format
            interval_map = {
                '1m': '1m',
                '5m': '5m',
                '15m': '15m',
                '1h': '1h',
                '4h': '4h',
                '1d': '1d',
            }
            
            if interval not in interval_map:
                raise ValueError(f"Invalid interval: {interval}")
            
            hl_interval = interval_map[interval]
            
            # Calculate start time (limit candles back)
            interval_seconds = self.INTERVAL_SECONDS[interval]
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = end_time - (interval_seconds * limit * 1000)
            
            # Fetch candles from Hyperliquid API
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": hl_interval,
                    "startTime": start_time,
                    "endTime": end_time
                }
            }
            
            response = requests.post(self.base_url, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if not data or len(data) == 0:
                logger.warning(f"No candle data returned for {symbol}")
                return self._create_empty_dataframe()
            
            # Parse candles
            candles = []
            for candle in data:
                candles.append({
                    'timestamp': pd.to_datetime(candle['t'], unit='ms'),
                    'open': float(candle['o']),
                    'high': float(candle['h']),
                    'low': float(candle['l']),
                    'close': float(candle['c']),
                    'volume': float(candle['v']),
                })
            
            df = pd.DataFrame(candles)
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            logger.info(f"Fetched {len(df)} candles for {symbol} ({interval})")
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch candles for {symbol}: {e}", exc_info=True)
            return self._create_empty_dataframe()
    
    def _create_empty_dataframe(self) -> pd.DataFrame:
        """Create empty DataFrame with proper columns."""
        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
