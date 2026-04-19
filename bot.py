"""Main Hyperliquid trading bot."""
import logging
import time
from typing import Optional, Dict
from datetime import datetime

from config import Config
from core.exchange import HyperliquidClient
from core.market_data import MarketData
from core.risk_manager import RiskManager
from strategies.factory import get_strategy
from strategies.base import SignalType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot orchestrator."""
    
    def __init__(self):
        """Initialize the trading bot."""
        logger.info("=" * 80)
        logger.info("Initializing Hyperliquid Trading Bot")
        logger.info("=" * 80)
        
        # Validate configuration
        Config.validate()
        
        # Initialize components
        self.client = HyperliquidClient(
            private_key=Config.PRIVATE_KEY,
            wallet_address=Config.WALLET_ADDRESS,
            testnet=Config.USE_TESTNET,
            dex=Config.DEX
        )
        
        self.market_data = MarketData(testnet=Config.USE_TESTNET, dex=Config.DEX)
        
        self.risk_manager = RiskManager(
            stop_loss_pct=Config.STOP_LOSS_PCT,
            take_profit_pct=Config.TAKE_PROFIT_PCT,
            max_open_positions=Config.MAX_OPEN_POSITIONS,
            max_daily_loss_usd=Config.MAX_DAILY_LOSS_USD
        )
        
        self.strategy = get_strategy(Config.STRATEGY)
        
        logger.info(f"Strategy: {self.strategy}")
        if Config.DEX:
            logger.info(f"HIP-3 Dex: {Config.DEX}")
        logger.info(f"Symbol: {Config.SYMBOL}")
        logger.info(f"Position Size: ${Config.POSITION_SIZE_USD}")
        logger.info(f"Leverage: {Config.MAX_LEVERAGE}x")
        logger.info(f"Candle Interval: {Config.CANDLE_INTERVAL}")
        logger.info(f"Loop Interval: {Config.LOOP_INTERVAL_SEC}s")
        logger.info("=" * 80)
        
        # Set initial leverage
        # HIP-3 perps require isolated margin
        is_cross = not Config.is_hip3()
        self.client.update_leverage(Config.SYMBOL, Config.MAX_LEVERAGE, is_cross=is_cross)
        
        # Track position state
        self.position_entry_price: Optional[float] = None
        self.position_type: Optional[str] = None  # 'LONG' or 'SHORT'
    
    def get_current_position(self) -> Optional[Dict]:
        """Get current position for the configured symbol."""
        position = self.client.get_position(Config.SYMBOL)
        
        if position:
            pos_data = position['position']
            size = float(pos_data['szi'])
            
            if size != 0:
                return {
                    'size': abs(size),
                    'type': 'LONG' if size > 0 else 'SHORT',
                    'entry_price': float(pos_data['entryPx']),
                    'unrealized_pnl': float(pos_data['unrealizedPnl'])
                }
        
        return None
    
    def update_position_tracking(self):
        """Update internal position tracking."""
        position = self.get_current_position()
        
        if position:
            self.position_entry_price = position['entry_price']
            self.position_type = position['type']
        else:
            self.position_entry_price = None
            self.position_type = None
    
    def check_risk_exit(self, current_price: float) -> Optional[str]:
        """Check if position should be exited due to risk management."""
        if not self.position_entry_price or not self.position_type:
            return None
        
        is_long = self.position_type == 'LONG'
        exit_reason = self.risk_manager.check_position_exit(
            self.position_entry_price,
            current_price,
            is_long
        )
        
        return exit_reason
    
    def execute_trade(self, signal_type: SignalType, reason: str):
        """Execute a trade based on signal."""
        logger.info(f"Executing trade: {signal_type.value} | Reason: {reason}")
        
        if signal_type == SignalType.LONG:
            result = self.client.place_market_order(
                symbol=Config.SYMBOL,
                is_buy=True,
                size_usd=Config.POSITION_SIZE_USD,
                leverage=Config.MAX_LEVERAGE
            )
            if result:
                logger.info("✓ LONG position opened")
        
        elif signal_type == SignalType.SHORT:
            result = self.client.place_market_order(
                symbol=Config.SYMBOL,
                is_buy=False,
                size_usd=Config.POSITION_SIZE_USD,
                leverage=Config.MAX_LEVERAGE
            )
            if result:
                logger.info("✓ SHORT position opened")
        
        elif signal_type in [SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT]:
            result = self.client.close_position(Config.SYMBOL)
            if result:
                logger.info("✓ Position closed")
        
        # Update position tracking after trade
        time.sleep(2)  # Wait for order to settle
        self.update_position_tracking()
    
    def run_strategy_loop(self):
        """Run one iteration of the strategy loop."""
        try:
            # Update position tracking
            self.update_position_tracking()
            
            # Get current price
            current_price = self.client.get_market_price(Config.SYMBOL)
            if not current_price:
                logger.warning("Failed to get current price")
                return
            
            # Check risk management exits first
            if self.position_type:
                exit_reason = self.check_risk_exit(current_price)
                if exit_reason:
                    logger.warning(f"Risk exit triggered: {exit_reason}")
                    self.execute_trade(
                        SignalType.CLOSE_LONG if self.position_type == 'LONG' else SignalType.CLOSE_SHORT,
                        exit_reason
                    )
                    return
            
            # Fetch market data
            df = self.market_data.fetch_candles(
                symbol=Config.SYMBOL,
                interval=Config.CANDLE_INTERVAL,
                limit=100
            )
            
            if df.empty:
                logger.warning("No market data available")
                return
            
            # Run strategy analysis
            signal = self.strategy.analyze(df, current_position=self.position_type)
            
            logger.info(f"Signal: {signal.signal_type.value} (strength={signal.strength:.2f}) | {signal.reason}")
            
            # Execute trades based on signal
            if signal.signal_type == SignalType.HOLD:
                # Show current position status
                if self.position_type:
                    position = self.get_current_position()
                    if position:
                        pnl = position['unrealized_pnl']
                        logger.info(f"Current {self.position_type} position | "
                                  f"Entry: ${self.position_entry_price:.2f} | "
                                  f"Current: ${current_price:.2f} | "
                                  f"PnL: ${pnl:.2f}")
                return
            
            # Check if we can open new positions
            if signal.signal_type in [SignalType.LONG, SignalType.SHORT]:
                if not self.risk_manager.can_open_position(1 if self.position_type else 0):
                    logger.warning("Cannot open new position due to risk limits")
                    return
            
            # Execute the trade
            self.execute_trade(signal.signal_type, signal.reason)
            
        except Exception as e:
            logger.error(f"Error in strategy loop: {e}", exc_info=True)
    
    def run(self):
        """Run the main bot loop."""
        logger.info("Bot started. Press Ctrl+C to stop.")
        
        try:
            while True:
                logger.info("-" * 80)
                logger.info(f"Loop iteration at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Check if trading is allowed (daily loss limit)
                if not self.risk_manager.can_trade():
                    logger.error("Trading paused due to daily loss limit!")
                    time.sleep(Config.LOOP_INTERVAL_SEC)
                    continue
                
                # Run strategy
                self.run_strategy_loop()
                
                # Sleep until next iteration
                logger.info(f"Sleeping for {Config.LOOP_INTERVAL_SEC}s...")
                time.sleep(Config.LOOP_INTERVAL_SEC)
                
        except KeyboardInterrupt:
            logger.info("\nShutdown signal received. Stopping bot...")
            logger.info("Bot stopped.")


def main():
    """Main entry point."""
    try:
        bot = TradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
