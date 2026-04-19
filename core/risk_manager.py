"""Risk management module."""
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages trading risk and position sizing."""
    
    def __init__(
        self,
        stop_loss_pct: float,
        take_profit_pct: float,
        max_open_positions: int,
        max_daily_loss_usd: float
    ):
        """
        Initialize risk manager.
        
        Args:
            stop_loss_pct: Stop loss percentage (e.g., 2.0 for 2%)
            take_profit_pct: Take profit percentage
            max_open_positions: Maximum number of concurrent open positions
            max_daily_loss_usd: Maximum daily loss in USD before stopping
        """
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_open_positions = max_open_positions
        self.max_daily_loss_usd = max_daily_loss_usd
        
        # Track daily P&L
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now().date()
        
        logger.info(f"Risk Manager initialized: SL={stop_loss_pct}%, "
                   f"TP={take_profit_pct}%, Max Positions={max_open_positions}, "
                   f"Max Daily Loss=${max_daily_loss_usd}")
    
    def reset_daily_pnl(self):
        """Reset daily P&L counter if it's a new day."""
        today = datetime.now().date()
        if today > self.last_reset_date:
            logger.info(f"New trading day. Previous daily P&L: ${self.daily_pnl:.2f}")
            self.daily_pnl = 0.0
            self.last_reset_date = today
    
    def update_daily_pnl(self, pnl: float):
        """Update daily P&L tracker."""
        self.reset_daily_pnl()
        self.daily_pnl += pnl
        logger.info(f"Daily P&L updated: ${self.daily_pnl:.2f}")
    
    def can_trade(self) -> bool:
        """Check if trading is allowed (daily loss limit not exceeded)."""
        self.reset_daily_pnl()
        
        if self.daily_pnl < -self.max_daily_loss_usd:
            logger.warning(f"Daily loss limit exceeded: ${self.daily_pnl:.2f} < "
                         f"-${self.max_daily_loss_usd}")
            return False
        
        return True
    
    def can_open_position(self, current_positions: int) -> bool:
        """Check if a new position can be opened."""
        if current_positions >= self.max_open_positions:
            logger.warning(f"Max positions limit reached: {current_positions} >= "
                         f"{self.max_open_positions}")
            return False
        
        return self.can_trade()
    
    def check_stop_loss(self, entry_price: float, current_price: float, is_long: bool) -> bool:
        """
        Check if stop loss is triggered.
        
        Args:
            entry_price: Position entry price
            current_price: Current market price
            is_long: True if long position, False if short
        
        Returns:
            True if stop loss triggered
        """
        if is_long:
            loss_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            loss_pct = ((entry_price - current_price) / entry_price) * 100
        
        if loss_pct < -self.stop_loss_pct:
            logger.warning(f"Stop loss triggered: {loss_pct:.2f}% < -{self.stop_loss_pct}%")
            return True
        
        return False
    
    def check_take_profit(self, entry_price: float, current_price: float, is_long: bool) -> bool:
        """
        Check if take profit is triggered.
        
        Args:
            entry_price: Position entry price
            current_price: Current market price
            is_long: True if long position, False if short
        
        Returns:
            True if take profit triggered
        """
        if is_long:
            profit_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        if profit_pct >= self.take_profit_pct:
            logger.info(f"Take profit triggered: {profit_pct:.2f}% >= {self.take_profit_pct}%")
            return True
        
        return False
    
    def check_position_exit(
        self,
        entry_price: float,
        current_price: float,
        is_long: bool
    ) -> Optional[str]:
        """
        Check if position should be exited (SL or TP).
        
        Returns:
            'stop_loss', 'take_profit', or None
        """
        if self.check_stop_loss(entry_price, current_price, is_long):
            return 'stop_loss'
        
        if self.check_take_profit(entry_price, current_price, is_long):
            return 'take_profit'
        
        return None
