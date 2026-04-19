"""Strategy factory for creating strategy instances."""
from .base import BaseStrategy
from .ema_crossover import EMACrossoverStrategy
from .rsi_mean_reversion import RSIMeanReversionStrategy
from .breakout import BreakoutStrategy
from .outcome_arb import OutcomeArbStrategy, ArbConfig, ArbSignal

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
}


def get_strategy(strategy_name: str, **params) -> BaseStrategy:
    """
    Get strategy instance by name with optional custom parameters.
    
    Args:
        strategy_name: Name of the strategy (ema_crossover, rsi_mean_reversion, breakout)
        **params: Override default strategy parameters (e.g. fast_period=12)
    
    Returns:
        Strategy instance
    
    Raises:
        ValueError: If strategy name is unknown
    """
    strategy_key = strategy_name.lower()

    if strategy_key not in STRATEGY_DEFAULTS:
        available = ', '.join(STRATEGY_DEFAULTS.keys())
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {available}")

    # Merge defaults with user overrides
    merged = {**STRATEGY_DEFAULTS[strategy_key], **params}

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
