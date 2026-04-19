# Hyperliquid Trading Bot

A fully-featured automated trading bot for Hyperliquid perpetual futures exchange with configurable strategies, risk management, and clean architecture.

## Features

- **Multiple Trading Strategies:**
  - EMA Crossover (fast/slow moving average crossover)
  - RSI Mean Reversion (oversold/overbought signals)
  - Breakout (support/resistance level breaks)

- **Risk Management:**
  - Configurable stop-loss and take-profit levels
  - Maximum position limits
  - Daily loss limits with automatic trading pause
  - Position size control

- **Exchange Integration:**
  - Full Hyperliquid API integration
  - Testnet and mainnet support
  - Real-time position tracking
  - Market and limit order execution

- **Monitoring:**
  - Detailed logging of all trades and signals
  - Real-time P&L tracking
  - Position monitoring

## Project Structure

```
hyperliquid-bot/
├── bot.py                    # Main bot entrypoint
├── config.py                 # Configuration loader
├── requirements.txt          # Python dependencies
├── .env.example             # Environment configuration template
├── core/
│   ├── __init__.py
│   ├── exchange.py          # Hyperliquid exchange client
│   ├── market_data.py       # Market data fetcher
│   └── risk_manager.py      # Risk management
└── strategies/
    ├── __init__.py
    ├── base.py              # Base strategy class
    ├── ema_crossover.py     # EMA crossover strategy
    ├── rsi_mean_reversion.py # RSI mean reversion strategy
    ├── breakout.py          # Breakout strategy
    └── factory.py           # Strategy factory
```

## Quick Start

### 1. Install Dependencies

```powershell
cd C:\Users\kdpet\hyperliquid-bot
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```powershell
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Your Hyperliquid wallet private key (hex, without 0x prefix)
PRIVATE_KEY=your_private_key_here

# Your wallet address
WALLET_ADDRESS=0xYourWalletAddressHere

# Use testnet (recommended for testing)
USE_TESTNET=true

# Trading parameters
SYMBOL=ETH
POSITION_SIZE_USD=100
MAX_LEVERAGE=5
STRATEGY=ema_crossover

# Risk management
STOP_LOSS_PCT=2.0
TAKE_PROFIT_PCT=4.0
MAX_OPEN_POSITIONS=3
MAX_DAILY_LOSS_USD=500

# Intervals
CANDLE_INTERVAL=15m
LOOP_INTERVAL_SEC=15
```

### 3. Run the Bot

```powershell
python bot.py
```

## Available Strategies

### 1. EMA Crossover (`ema_crossover`)
- **Logic:** Buys when fast EMA crosses above slow EMA, sells when it crosses below
- **Parameters:** Fast period (9), Slow period (21)
- **Best for:** Trending markets

### 2. RSI Mean Reversion (`rsi_mean_reversion`)
- **Logic:** Buys when RSI < 30 (oversold), sells when RSI > 70 (overbought)
- **Parameters:** RSI period (14), oversold (30), overbought (70)
- **Best for:** Range-bound markets

### 3. Breakout (`breakout`)
- **Logic:** Buys on resistance break, sells on support break
- **Parameters:** Lookback period (20), breakout threshold (0.5%)
- **Best for:** Volatile markets with clear support/resistance

## Configuration Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `PRIVATE_KEY` | Your wallet private key | Required |
| `WALLET_ADDRESS` | Your wallet address | Required |
| `USE_TESTNET` | Use testnet (true/false) | true |
| `SYMBOL` | Trading symbol (ETH, BTC, SOL, etc.) | ETH |
| `POSITION_SIZE_USD` | Position size in USD | 100 |
| `MAX_LEVERAGE` | Maximum leverage (1-50) | 5 |
| `STRATEGY` | Strategy to use | ema_crossover |
| `STOP_LOSS_PCT` | Stop-loss percentage | 2.0 |
| `TAKE_PROFIT_PCT` | Take-profit percentage | 4.0 |
| `MAX_OPEN_POSITIONS` | Max concurrent positions | 3 |
| `MAX_DAILY_LOSS_USD` | Max daily loss before pause | 500 |
| `CANDLE_INTERVAL` | Candle timeframe (1m/5m/15m/1h/4h/1d) | 15m |
| `LOOP_INTERVAL_SEC` | Bot loop interval in seconds | 15 |

## Safety Features

1. **Stop-Loss Protection:** Automatically closes positions when loss exceeds configured percentage
2. **Take-Profit Targets:** Locks in profits when target is reached
3. **Daily Loss Limits:** Pauses trading if daily loss exceeds threshold
4. **Position Limits:** Prevents over-leveraging with max position count
5. **Testnet Support:** Test strategies risk-free on Hyperliquid testnet

## Getting Your Hyperliquid Credentials

### For Testnet (Recommended for Testing):
1. Visit [Hyperliquid Testnet](https://app.hyperliquid-testnet.xyz/)
2. Create a new wallet or import existing one
3. Get testnet funds from the faucet
4. Export your private key from wallet settings

### For Mainnet (Real Trading):
1. Visit [Hyperliquid](https://app.hyperliquid.xyz/)
2. Connect your wallet (MetaMask, WalletConnect, etc.)
3. Deposit funds
4. Export your private key (**Keep this secure!**)

⚠️ **Security Warning:** Never share your private key. Never commit it to git. Use testnet for development.

## Monitoring Your Bot

The bot logs all activity in real-time:

```
2026-02-16 14:30:00 [INFO] Signal: LONG (strength=0.85) | Bullish EMA crossover
2026-02-16 14:30:02 [INFO] ✓ LONG position opened
2026-02-16 14:30:45 [INFO] Current LONG position | Entry: $2500.00 | Current: $2510.00 | PnL: $8.50
```

## Adding Custom Strategies

Create a new strategy by extending `BaseStrategy`:

```python
# strategies/my_strategy.py
from .base import BaseStrategy, Signal, SignalType

class MyStrategy(BaseStrategy):
    def analyze(self, df, current_position=None):
        # Your strategy logic here
        return Signal(SignalType.LONG, strength=0.8, reason="My custom signal")
```

Register it in `strategies/factory.py`:

```python
'my_strategy': lambda: MyStrategy(),
```

## Troubleshooting

**"Configuration errors: PRIVATE_KEY must be set"**
- Make sure you copied `.env.example` to `.env` and filled in your credentials

**"Failed to get market price"**
- Check your internet connection
- Verify the symbol exists on Hyperliquid (e.g., 'ETH', 'BTC', 'SOL')

**"Max positions limit reached"**
- Increase `MAX_OPEN_POSITIONS` in `.env` or close existing positions

**Orders not executing:**
- Ensure you have sufficient balance in your account
- Check leverage settings (Hyperliquid max is 50x)
- Verify you're using the correct network (testnet vs mainnet)

## Disclaimer

⚠️ **WARNING:** This bot is for educational purposes. Cryptocurrency trading carries significant risk. 

- **Test thoroughly on testnet before using real funds**
- **Never invest more than you can afford to lose**
- **Past performance does not guarantee future results**
- **The developers are not responsible for any financial losses**

Use at your own risk!

## License

MIT License - Use freely, but at your own risk.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Hyperliquid documentation: https://hyperliquid.gitbook.io/
3. Ensure all dependencies are installed correctly

---

**Happy Trading! 🚀**
