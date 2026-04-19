"""Configuration loader for Hyperliquid trading bot."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Bot configuration."""
    
    # Hyperliquid credentials
    PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
    WALLET_ADDRESS = os.getenv('WALLET_ADDRESS', '')
    USE_TESTNET = os.getenv('USE_TESTNET', 'true').lower() == 'true'
    
    # Market selection
    DEX = os.getenv('DEX', '')  # '' = native perps, 'cash' = HIP-3 commodities/stocks
    SYMBOL = os.getenv('SYMBOL', 'ETH')
    
    # Trading parameters
    POSITION_SIZE_USD = float(os.getenv('POSITION_SIZE_USD', '100'))
    MAX_LEVERAGE = int(os.getenv('MAX_LEVERAGE', '5'))
    STRATEGY = os.getenv('STRATEGY', 'ema_crossover')
    
    # Known HIP-3 dex prefixes (symbol format is "dex:COIN")
    HIP3_PREFIXES = ("cash:", "xyz:")

    @classmethod
    def is_hip3(cls) -> bool:
        """Whether we are trading on a HIP-3 builder-deployed dex."""
        return bool(cls.DEX)

    @staticmethod
    def is_hip3_symbol(symbol: str) -> bool:
        """Whether a symbol belongs to a HIP-3 builder-deployed dex."""
        return any(symbol.startswith(p) for p in Config.HIP3_PREFIXES)

    @staticmethod
    def dex_for_symbol(symbol: str) -> str:
        """Return the dex key for a symbol ('' for native perps)."""
        for prefix in Config.HIP3_PREFIXES:
            if symbol.startswith(prefix):
                return prefix.rstrip(':')
        return ""
    
    # Timeframe-specific SL/TP defaults (stop_loss%, take_profit%, recommended_leverage)
    TIMEFRAME_DEFAULTS = {
        '1m':  {'sl': 0.3,  'tp': 0.6,  'lev': 10, 'style': 'Scalp'},
        '5m':  {'sl': 0.5,  'tp': 1.0,  'lev': 7,  'style': 'Scalp'},
        '15m': {'sl': 1.0,  'tp': 2.0,  'lev': 5,  'style': 'Day Trade'},
        '1h':  {'sl': 2.0,  'tp': 4.0,  'lev': 3,  'style': 'Swing'},
        '4h':  {'sl': 3.5,  'tp': 7.0,  'lev': 2,  'style': 'Swing'},
        '1d':  {'sl': 5.0,  'tp': 10.0, 'lev': 1,  'style': 'Position'},
    }

    # Risk management
    STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', '2.0'))
    TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', '4.0'))
    MAX_OPEN_POSITIONS = int(os.getenv('MAX_OPEN_POSITIONS', '3'))
    MAX_DAILY_LOSS_USD = float(os.getenv('MAX_DAILY_LOSS_USD', '500'))
    
    # Intervals
    CANDLE_INTERVAL = os.getenv('CANDLE_INTERVAL', '15m')
    LOOP_INTERVAL_SEC = int(os.getenv('LOOP_INTERVAL_SEC', '15'))

    # Email notifications
    EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')   # Gmail: use App Password
    EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT', '')  # defaults to sender

    # Telegram notifications
    TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'false').lower() == 'true'
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

    # Higher-timeframe mapping for multi-TF confirmation (per-slot)
    MTF_MAP = {
        '1m': '15m',
        '5m': '1h',
        '15m': '4h',
        '1h': '4h',
        '4h': '1d',
        '1d': '1d',
    }

    # Multi-position slots (up to 5).
    # Each slot: {symbol, interval, strategy, sl, tp, leverage, enabled}
    # Stored in .env as SLOT_1=BTC|15m|ema_crossover|1.0|2.0|5  etc.
    MAX_SLOTS = 5
    POSITION_SLOTS: list[dict] = []

    @classmethod
    def _parse_slots(cls):
        """Parse SLOT_1..SLOT_5 from env into POSITION_SLOTS list."""
        cls.POSITION_SLOTS = []
        for i in range(1, cls.MAX_SLOTS + 1):
            raw = os.getenv(f'SLOT_{i}', '')
            if raw:
                parts = raw.split('|')
                if len(parts) >= 6:
                    d = cls.get_timeframe_defaults(parts[1])
                    # Parse optional size_usd (index 7) and strategy_params JSON (index 8)
                    size_usd = float(parts[7]) if len(parts) > 7 and parts[7] else 100.0
                    strategy_params = {}
                    if len(parts) > 8:
                        try:
                            import json
                            strategy_params = json.loads(parts[8])
                        except Exception:
                            pass
                    # Parse trailing_sl flag (index 9)
                    trailing_sl = False
                    if len(parts) > 9:
                        trailing_sl = parts[9].lower() == 'true'
                    # Parse mtf_enabled flag (index 10)
                    mtf_enabled = True
                    if len(parts) > 10:
                        mtf_enabled = parts[10].lower() == 'true'
                    # Parse new enhancement flags (indices 11-14)
                    regime_filter = False
                    if len(parts) > 11:
                        regime_filter = parts[11].lower() == 'true'
                    atr_stops = False
                    if len(parts) > 12:
                        atr_stops = parts[12].lower() == 'true'
                    loss_cooldown = False
                    if len(parts) > 13:
                        loss_cooldown = parts[13].lower() == 'true'
                    volume_confirm = False
                    if len(parts) > 14:
                        volume_confirm = parts[14].lower() == 'true'
                    rsi_guard = False
                    if len(parts) > 15:
                        rsi_guard = parts[15].lower() == 'true'
                    rsi_guard_low = 30.0
                    if len(parts) > 16:
                        try: rsi_guard_low = float(parts[16])
                        except ValueError: pass
                    rsi_guard_high = 70.0
                    if len(parts) > 17:
                        try: rsi_guard_high = float(parts[17])
                        except ValueError: pass
                    cls.POSITION_SLOTS.append({
                        'slot': i,
                        'symbol': parts[0],
                        'interval': parts[1],
                        'strategy': parts[2],
                        'sl': float(parts[3]),
                        'tp': float(parts[4]),
                        'leverage': int(parts[5]),
                        'enabled': parts[6].lower() == 'true' if len(parts) > 6 else True,
                        'size_usd': size_usd,
                        'strategy_params': strategy_params,
                        'trailing_sl': trailing_sl,
                        'mtf_enabled': mtf_enabled,
                        'regime_filter': regime_filter,
                        'atr_stops': atr_stops,
                        'loss_cooldown': loss_cooldown,
                        'volume_confirm': volume_confirm,
                        'rsi_guard': rsi_guard,
                        'rsi_guard_low': rsi_guard_low,
                        'rsi_guard_high': rsi_guard_high,
                    })
            else:
                # Empty slot placeholder
                cls.POSITION_SLOTS.append({
                    'slot': i,
                    'symbol': '',
                    'interval': '15m',
                    'strategy': 'ema_crossover',
                    'sl': 1.0,
                    'tp': 2.0,
                    'leverage': 5,
                    'enabled': False,
                    'size_usd': 100.0,
                    'strategy_params': {},
                    'trailing_sl': False,
                    'mtf_enabled': True,
                    'regime_filter': False,
                    'atr_stops': False,
                    'loss_cooldown': False,
                    'volume_confirm': False,
                    'rsi_guard': False,
                    'rsi_guard_low': 30.0,
                    'rsi_guard_high': 70.0,
                })

    @classmethod
    def get_active_slots(cls) -> list[dict]:
        """Return only enabled slots with a symbol set."""
        return [s for s in cls.POSITION_SLOTS if s.get('enabled') and s.get('symbol')]

    @classmethod
    def slot_to_env(cls, slot: dict) -> str:
        """Serialise a slot dict to the SLOT_N env format."""
        import json
        sp = json.dumps(slot.get('strategy_params', {}))
        size = slot.get('size_usd', 100)
        trail = 'true' if slot.get('trailing_sl') else 'false'
        mtf = 'true' if slot.get('mtf_enabled', True) else 'false'
        regime = 'true' if slot.get('regime_filter') else 'false'
        atr = 'true' if slot.get('atr_stops') else 'false'
        cooldown = 'true' if slot.get('loss_cooldown') else 'false'
        vol = 'true' if slot.get('volume_confirm') else 'false'
        rsi_g = 'true' if slot.get('rsi_guard') else 'false'
        rsi_g_low = slot.get('rsi_guard_low', 30)
        rsi_g_high = slot.get('rsi_guard_high', 70)
        return (f"{slot['symbol']}|{slot['interval']}|{slot['strategy']}"
                f"|{slot['sl']}|{slot['tp']}|{slot['leverage']}"
                f"|{'true' if slot.get('enabled') else 'false'}"
                f"|{size}"
                f"|{sp}"
                f"|{trail}"
                f"|{mtf}"
                f"|{regime}"
                f"|{atr}"
                f"|{cooldown}"
                f"|{vol}"
                f"|{rsi_g}"
                f"|{rsi_g_low}"
                f"|{rsi_g_high}")

    @classmethod
    def get_timeframe_defaults(cls, interval: str) -> dict:
        """Return recommended SL/TP/leverage for a given candle interval."""
        return cls.TIMEFRAME_DEFAULTS.get(interval, cls.TIMEFRAME_DEFAULTS['15m'])

    @classmethod
    def apply_timeframe_defaults(cls, interval: str):
        """Set SL/TP/leverage from timeframe defaults."""
        d = cls.get_timeframe_defaults(interval)
        cls.STOP_LOSS_PCT = d['sl']
        cls.TAKE_PROFIT_PCT = d['tp']
        cls.MAX_LEVERAGE = d['lev']
        cls.CANDLE_INTERVAL = interval
    
    @classmethod
    def validate(cls):
        """Validate required configuration."""
        cls._parse_slots()
        errors = []
        
        if not cls.PRIVATE_KEY or cls.PRIVATE_KEY == 'your_private_key_here':
            errors.append('PRIVATE_KEY must be set in .env file')
        
        if not cls.WALLET_ADDRESS or cls.WALLET_ADDRESS.startswith('0xYour'):
            errors.append('WALLET_ADDRESS must be set in .env file')
        
        max_lev = 50 if not cls.is_hip3_symbol(cls.SYMBOL) else 50
        if cls.MAX_LEVERAGE < 1 or cls.MAX_LEVERAGE > max_lev:
            errors.append(f'MAX_LEVERAGE must be between 1 and {max_lev}')
        
        if cls.is_hip3() and ':' not in cls.SYMBOL:
            errors.append(f'HIP-3 symbols must use dex:coin format (e.g. cash:GOLD, xyz:TSLA), got: {cls.SYMBOL}')
        
        if errors:
            raise ValueError(f"Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
        
        return True
