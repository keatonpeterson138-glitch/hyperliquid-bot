"""Maps Hyperliquid HIP-3 symbols to underlying tickers.

Used by yfinance / Polygon / similar equity+commodity adapters to resolve
``xyz:TSLA`` → ``TSLA``, ``cash:GOLD`` → ``GC=F``, etc.

Add new HIP-3 listings here as Hyperliquid deploys them.
"""
from __future__ import annotations

# Maps HIP-3 symbol → underlying yfinance ticker.
# Stocks (trade.xyz):
HIP3_TO_YFINANCE: dict[str, str] = {
    "xyz:NVDA": "NVDA",
    "xyz:TSLA": "TSLA",
    "xyz:AAPL": "AAPL",
    "xyz:MSFT": "MSFT",
    "xyz:GOOGL": "GOOGL",
    "xyz:AMZN": "AMZN",
    "xyz:META": "META",
    "xyz:HOOD": "HOOD",
    "xyz:INTC": "INTC",
    "xyz:PLTR": "PLTR",
    "xyz:COIN": "COIN",
    "xyz:NFLX": "NFLX",
    "xyz:MSTR": "MSTR",
    "xyz:AMD": "AMD",
    "xyz:TSM": "TSM",
    # Indices via ETF proxies for long history.
    "xyz:SP500": "SPY",
    "xyz:XYZ100": "QQQ",
    # Commodities via continuous front-month futures.
    "cash:GOLD": "GC=F",
    "cash:SILVER": "SI=F",
    "cash:OIL": "CL=F",
    "cash:CORN": "ZC=F",
    "cash:WHEAT": "ZW=F",
}


def yfinance_ticker_for(symbol: str) -> str | None:
    """Resolve an HIP-3 or underlying symbol to its yfinance ticker.

    Returns None if the symbol isn't mapped. Non-HIP-3 tickers (e.g.,
    ``TSLA``) pass through unchanged.
    """
    if symbol in HIP3_TO_YFINANCE:
        return HIP3_TO_YFINANCE[symbol]
    if ":" in symbol:
        # Unknown HIP-3 dex/coin — can't resolve.
        return None
    # Assume caller passed an equity/commodity ticker directly.
    return symbol
