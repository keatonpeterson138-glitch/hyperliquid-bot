"""Preset slot configurations — backtested winners ready to instantiate.

Numbers come from ``scripts/run_preset_bench.py`` (see preset_bench.csv).
Each entry has the historical metrics so the UI can show the user *why*
this preset is here, plus a complete ``SlotCreate`` body so creating it
is one POST.

Curation rule: WR >= 75% AND Sharpe > 0 AND total return > 0 AND >= 50
trades. The CL=F keltner pair (75.6% WR but -15% return) is intentionally
excluded.

When you want to add a new winner: re-run the bench, copy the row from
``preset_bench_winners.csv`` into this list. The schema mirrors
``backend/api/slots.py`` ``SlotCreate``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PresetSlot:
    """One ready-to-go slot config + the backtest evidence behind it."""

    preset_id: str
    name: str
    description: str
    # Backtest evidence (ranges over the test window).
    backtest_window_years: int
    win_rate: float          # 0.0 - 1.0
    sharpe: float
    total_return_pct: float
    trade_count: int
    max_drawdown_pct: float
    # Slot config — passed straight to POST /slots.
    slot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


PRESETS: list[PresetSlot] = [
    PresetSlot(
        preset_id="keltner_spy_d1",
        name="Keltner Reversion · SPY",
        description=(
            "Buy SPY when it pokes below the lower Keltner channel with RSI(14) < 30. "
            "Sell at the channel midline. Highest win-rate of all 35 backtested pairs."
        ),
        backtest_window_years=20,
        win_rate=0.800,
        sharpe=2.39,
        total_return_pct=10.97,
        trade_count=60,
        max_drawdown_pct=0.0,
        slot={
            "symbol": "SPY",
            "interval": "1d",
            "strategy": "keltner_reversion",
            "size_usd": 1000.0,
            "leverage": 1,
            "stop_loss_pct": 2.5,
            "take_profit_pct": None,
            "enabled": False,
            "strategy_params": {
                "ema_period": 20, "atr_period": 14, "atr_mult": 1.5,
                "rsi_period": 14, "rsi_oversold": 30.0, "stop_pct": 0.025,
            },
        },
    ),
    PresetSlot(
        preset_id="williams_spy_d1",
        name="Williams %R · SPY",
        description=(
            "Buy SPY on deep Williams %R oversold (<-90) inside the SMA-200 uptrend. "
            "Sell on first cross above EMA-5 — quick mean-revert pop."
        ),
        backtest_window_years=20,
        win_rate=0.777,
        sharpe=2.99,
        total_return_pct=5.41,
        trade_count=94,
        max_drawdown_pct=0.0,
        slot={
            "symbol": "SPY",
            "interval": "1d",
            "strategy": "williams_mean_rev",
            "size_usd": 1000.0,
            "leverage": 1,
            "stop_loss_pct": 2.0,
            "take_profit_pct": None,
            "enabled": False,
            "strategy_params": {
                "wr_period": 14, "wr_oversold": -90.0, "wr_overbought": -30.0,
                "trend_sma": 200, "exit_ema": 5, "stop_pct": 0.02,
            },
        },
    ),
    PresetSlot(
        preset_id="keltner_qqq_d1",
        name="Keltner Reversion · QQQ",
        description=(
            "Same Keltner setup as SPY but on the Nasdaq-100 ETF. "
            "Slightly higher volatility = bigger winners but a few more losers."
        ),
        backtest_window_years=20,
        win_rate=0.792,
        sharpe=1.86,
        total_return_pct=9.28,
        trade_count=53,
        max_drawdown_pct=0.0,
        slot={
            "symbol": "QQQ",
            "interval": "1d",
            "strategy": "keltner_reversion",
            "size_usd": 1000.0,
            "leverage": 1,
            "stop_loss_pct": 2.5,
            "take_profit_pct": None,
            "enabled": False,
            "strategy_params": {
                "ema_period": 20, "atr_period": 14, "atr_mult": 1.5,
                "rsi_period": 14, "rsi_oversold": 30.0, "stop_pct": 0.025,
            },
        },
    ),
    PresetSlot(
        preset_id="williams_qqq_d1",
        name="Williams %R · QQQ",
        description=(
            "Williams %R deep-oversold trend-filtered on Nasdaq-100. "
            "Highest Sharpe of the entire winners set (3.17)."
        ),
        backtest_window_years=20,
        win_rate=0.779,
        sharpe=3.17,
        total_return_pct=8.43,
        trade_count=104,
        max_drawdown_pct=0.0,
        slot={
            "symbol": "QQQ",
            "interval": "1d",
            "strategy": "williams_mean_rev",
            "size_usd": 1000.0,
            "leverage": 1,
            "stop_loss_pct": 2.0,
            "take_profit_pct": None,
            "enabled": False,
            "strategy_params": {
                "wr_period": 14, "wr_oversold": -90.0, "wr_overbought": -30.0,
                "trend_sma": 200, "exit_ema": 5, "stop_pct": 0.02,
            },
        },
    ),
]


def list_presets() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PRESETS]


def get_preset(preset_id: str) -> PresetSlot | None:
    for p in PRESETS:
        if p.preset_id == preset_id:
            return p
    return None
