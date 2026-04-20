"""Tests for strategies.factory.get_strategy.

Verifies the factory constructs the three pure-pandas strategies cleanly
and raises on unknown names. ``outcome_arb`` is skipped here because its
constructor pulls in ``core.outcome_client.OutcomeClient`` which needs
network access — covered separately in integration tests.
"""
from __future__ import annotations

import pytest

from strategies.base import BaseStrategy
from strategies.breakout import BreakoutStrategy
from strategies.ema_crossover import EMACrossoverStrategy
from strategies.factory import STRATEGY_DEFAULTS, get_strategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy


class TestStrategyFactory:
    def test_ema_crossover_constructs_with_defaults(self) -> None:
        strat = get_strategy("ema_crossover")
        assert isinstance(strat, EMACrossoverStrategy)
        assert isinstance(strat, BaseStrategy)
        assert strat.fast_period == STRATEGY_DEFAULTS["ema_crossover"]["fast_period"]
        assert strat.slow_period == STRATEGY_DEFAULTS["ema_crossover"]["slow_period"]

    def test_rsi_constructs_with_defaults(self) -> None:
        strat = get_strategy("rsi_mean_reversion")
        assert isinstance(strat, RSIMeanReversionStrategy)
        assert strat.period == STRATEGY_DEFAULTS["rsi_mean_reversion"]["period"]
        assert strat.oversold == STRATEGY_DEFAULTS["rsi_mean_reversion"]["oversold"]
        assert strat.overbought == STRATEGY_DEFAULTS["rsi_mean_reversion"]["overbought"]

    def test_breakout_constructs_with_defaults(self) -> None:
        strat = get_strategy("breakout")
        assert isinstance(strat, BreakoutStrategy)
        assert strat.lookback_period == STRATEGY_DEFAULTS["breakout"]["lookback_period"]

    def test_param_overrides_are_applied(self) -> None:
        strat = get_strategy("ema_crossover", fast_period=5, slow_period=13)
        assert isinstance(strat, EMACrossoverStrategy)
        assert strat.fast_period == 5
        assert strat.slow_period == 13

    def test_param_types_are_coerced(self) -> None:
        # Factory passes merged params through int()/float() — strings that
        # parse as numbers must not raise.
        strat = get_strategy("rsi_mean_reversion", period="10", oversold="25.0")
        assert strat.period == 10
        assert strat.oversold == 25

    def test_unknown_strategy_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown strategy"):
            get_strategy("nonexistent_strategy")

    def test_case_insensitive_name_matching(self) -> None:
        strat = get_strategy("EMA_Crossover")
        assert isinstance(strat, EMACrossoverStrategy)
