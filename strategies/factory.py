"""Strategy factory for creating strategy instances."""
from .base import BaseStrategy
from .bb_fade import BBFadeStrategy
from .breakout import BreakoutStrategy
from .connors_rsi2 import ConnorsRSI2Strategy
from .ema_crossover import EMACrossoverStrategy
from .gap_fill import GapFillStrategy
from .keltner_reversion import KeltnerReversionStrategy
from .outcome_arb import OutcomeArbStrategy, ArbConfig, ArbSignal
from .rsi_mean_reversion import RSIMeanReversionStrategy
from .williams_mean_rev import WilliamsMeanRevStrategy

# Default parameters for each strategy (used when no overrides supplied)
STRATEGY_DEFAULTS = {
    'ema_crossover': {
        'fast_period': 9,
        'slow_period': 21,
    },
    'rsi_mean_reversion': {
        'period': 14,
        'oversold': 30,
        'overbought': 70,
    },
    'breakout': {
        'lookback_period': 20,
        'breakout_threshold_pct': 0.5,
    },
    'outcome_arb': {
        'min_edge': 0.03,
        'kelly_fraction': 0.25,
        'max_size_per_outcome': 100.0,
        'max_total_exposure': 500.0,
        'default_vol': 0.80,
    },
    'connors_rsi2': {
        'trend_ema': 200,
        'rsi_period': 2,
        'oversold': 10.0,
        'exit_ema': 5,
        'stop_pct': 0.025,
    },
    'bb_fade': {
        'bb_period': 20,
        'bb_std': 2.0,
        'adx_period': 14,
        'adx_max': 25.0,
        'stop_pct': 0.02,
    },
    'keltner_reversion': {
        'ema_period': 20,
        'atr_period': 14,
        'atr_mult': 1.5,
        'rsi_period': 14,
        'rsi_oversold': 30.0,
        'stop_pct': 0.025,
    },
    'williams_mean_rev': {
        'wr_period': 14,
        'wr_oversold': -90.0,
        'wr_overbought': -30.0,
        'trend_sma': 200,
        'exit_ema': 5,
        'stop_pct': 0.02,
    },
    'gap_fill': {
        'gap_pct': 0.005,
        'vol_mult': 1.2,
        'vol_period': 20,
        'stop_pct': 0.015,
    },
}


def get_strategy(strategy_name: str, params: dict | None = None, /, **kwparams) -> BaseStrategy:
    """
    Get strategy instance by name with optional custom parameters.

    Accepts both call forms so the backtest engine (which passes params as
    a positional dict) and the old kwargs style both work:
        get_strategy("ema_crossover", fast_period=12)
        get_strategy("ema_crossover", {"fast_period": 12})

    Raises:
        ValueError: If strategy name is unknown
    """
    strategy_key = strategy_name.lower()

    if strategy_key not in STRATEGY_DEFAULTS:
        available = ', '.join(STRATEGY_DEFAULTS.keys())
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {available}")

    # Merge defaults with user overrides (positional dict first, then kwargs).
    merged = {**STRATEGY_DEFAULTS[strategy_key], **(params or {}), **kwparams}

    if strategy_key == 'ema_crossover':
        return EMACrossoverStrategy(
            fast_period=int(merged['fast_period']),
            slow_period=int(merged['slow_period']),
        )
    elif strategy_key == 'rsi_mean_reversion':
        return RSIMeanReversionStrategy(
            period=int(merged['period']),
            oversold=int(merged['oversold']),
            overbought=int(merged['overbought']),
        )
    elif strategy_key == 'breakout':
        return BreakoutStrategy(
            lookback_period=int(merged['lookback_period']),
            breakout_threshold_pct=float(merged['breakout_threshold_pct']),
        )
    elif strategy_key == 'connors_rsi2':
        return ConnorsRSI2Strategy(
            trend_ema=int(merged['trend_ema']),
            rsi_period=int(merged['rsi_period']),
            oversold=float(merged['oversold']),
            exit_ema=int(merged['exit_ema']),
            stop_pct=float(merged['stop_pct']),
        )
    elif strategy_key == 'bb_fade':
        return BBFadeStrategy(
            bb_period=int(merged['bb_period']),
            bb_std=float(merged['bb_std']),
            adx_period=int(merged['adx_period']),
            adx_max=float(merged['adx_max']),
            stop_pct=float(merged['stop_pct']),
        )
    elif strategy_key == 'keltner_reversion':
        return KeltnerReversionStrategy(
            ema_period=int(merged['ema_period']),
            atr_period=int(merged['atr_period']),
            atr_mult=float(merged['atr_mult']),
            rsi_period=int(merged['rsi_period']),
            rsi_oversold=float(merged['rsi_oversold']),
            stop_pct=float(merged['stop_pct']),
        )
    elif strategy_key == 'williams_mean_rev':
        return WilliamsMeanRevStrategy(
            wr_period=int(merged['wr_period']),
            wr_oversold=float(merged['wr_oversold']),
            wr_overbought=float(merged['wr_overbought']),
            trend_sma=int(merged['trend_sma']),
            exit_ema=int(merged['exit_ema']),
            stop_pct=float(merged['stop_pct']),
        )
    elif strategy_key == 'gap_fill':
        return GapFillStrategy(
            gap_pct=float(merged['gap_pct']),
            vol_mult=float(merged['vol_mult']),
            vol_period=int(merged['vol_period']),
            stop_pct=float(merged['stop_pct']),
        )
    elif strategy_key == 'outcome_arb':
        # OutcomeArbStrategy requires OutcomeClient and PriceBinaryModel
        # which can't be created here — return an ArbConfig for the caller
        # to construct the strategy with.  If client/model were passed in
        # params, we build the full strategy.
        from core.outcome_client import OutcomeClient
        from core.pricing_model import PriceBinaryModel
        client = merged.pop('outcome_client', None)
        model = merged.pop('pricing_model', None)
        if client is None:
            client = OutcomeClient(testnet=merged.pop('testnet', True))
        if model is None:
            model = PriceBinaryModel(client)
        cfg = ArbConfig(
            min_edge=float(merged.get('min_edge', 0.03)),
            kelly_fraction=float(merged.get('kelly_fraction', 0.25)),
            max_size_per_outcome=float(merged.get('max_size_per_outcome', 100.0)),
            max_total_exposure=float(merged.get('max_total_exposure', 500.0)),
            default_vol=float(merged.get('default_vol', 0.80)),
        )
        return OutcomeArbStrategy(client, model, config=cfg)
