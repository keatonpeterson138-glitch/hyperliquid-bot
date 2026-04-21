# Trading Presets — Backtested Report Card

This is the source of truth for the preset slot library shipped in the app
(Sidebar → Slots → "Backtested presets"). Numbers come from
[`scripts/run_preset_bench.py`](../scripts/run_preset_bench.py) and are
written to `data/preset_bench.csv` / `data/preset_bench_winners.csv` after
every run.

**Last regenerated:** 2026-04-20

---

## Strategy library

Five high-WR mean-reversion / pattern setups, all in [`strategies/`](../strategies):

| Strategy | File | Core idea |
|---|---|---|
| `connors_rsi2` | [connors_rsi2.py](../strategies/connors_rsi2.py) | Larry Connors classic — RSI(2) < 10 in SMA-200 uptrend, exit on first up-close |
| `bb_fade` | [bb_fade.py](../strategies/bb_fade.py) | Fade lower Bollinger band, ADX(14) < 25 only (range-bound regime) |
| `keltner_reversion` | [keltner_reversion.py](../strategies/keltner_reversion.py) | Buy below lower Keltner channel + RSI(14) < 30, exit at midline |
| `williams_mean_rev` | [williams_mean_rev.py](../strategies/williams_mean_rev.py) | Williams %R(14) < -90 in SMA-200 uptrend, exit on EMA-5 cross |
| `gap_fill` | [gap_fill.py](../strategies/gap_fill.py) | Daily gap > 0.5% with volume confirm, fade to prior close |

All long-only. Short variants of mean-reversion strategies historically
underperform in equities/crypto due to long-side drift.

---

## Full report card (35 pairs)

Backtest engine: `BacktestEngine` (see `backend/services/backtest/`), 1 trade
per signal, $1,000 per trade, 5 bps fees, 2 bps slippage. Lookback per asset
in the table below. Daily timeframe across the board.

```
Strategy               Asset    #     WR     Sharpe  MaxDD   Return
-------------------------------------------------------------------
connors_rsi2           BTC     135   53.3%    0.54   0.0%    +0.84%
bb_fade                BTC       7   71.4%    1.52   0.0%    +1.51%
keltner_reversion      BTC      11   72.7%    3.60   0.0%    +7.91%
williams_mean_rev      BTC      14   92.9%    4.85   0.0%    +6.41%
gap_fill               BTC       0      —       —      —        —
connors_rsi2           ETH      43   46.5%   -0.68   0.0%    -0.55%
bb_fade                ETH       4   75.0%    1.11   0.0%    +0.84%
keltner_reversion      ETH       8   62.5%    0.05   0.0%    -0.05%
williams_mean_rev      ETH       4   75.0%    3.42   0.0%    +1.64%
gap_fill               ETH       0      —       —      —        —
connors_rsi2           SPY     536   54.7%   -2.31   0.0%    -4.74%
bb_fade                SPY      50   68.0%    0.40   0.0%    +1.69%
keltner_reversion      SPY      60   80.0%    2.39   0.0%   +10.97%   ✅
williams_mean_rev      SPY      94   77.7%    2.99   0.0%    +5.41%   ✅
gap_fill               SPY     377   52.3%   -1.72   0.0%    -5.56%
connors_rsi2           QQQ     552   54.7%   -1.80   0.0%    -4.78%
bb_fade                QQQ      43   74.4%    1.97   0.0%    +6.78%
keltner_reversion      QQQ      53   79.2%    1.86   0.0%    +9.28%   ✅
williams_mean_rev      QQQ     104   77.9%    3.17   0.0%    +8.43%   ✅
gap_fill               QQQ     434   52.1%   -0.20   0.0%    -0.77%
connors_rsi2           TSLA    363   51.5%   -1.01   0.0%    -5.82%
bb_fade                TSLA     35   62.9%    0.36   0.0%    +1.92%
keltner_reversion      TSLA     45   64.4%    1.69   0.0%   +11.35%
williams_mean_rev      TSLA     61   67.2%    0.70   0.0%    +3.73%
gap_fill               TSLA    439   48.3%   -1.80   0.0%   -12.72%
connors_rsi2           GC=F    476   56.3%   -2.10   0.0%    -5.09%
bb_fade                GC=F     54   70.4%    1.43   0.0%    +3.55%
keltner_reversion      GC=F     60   73.3%    1.64   0.0%    +4.69%
williams_mean_rev      GC=F    104   72.1%    1.75   0.0%    +4.02%
gap_fill               GC=F    130   50.0%   -2.32   0.0%    -2.76%
connors_rsi2           CL=F    220   50.5%   -1.24   0.0%    -3.06%
bb_fade                CL=F     31   67.7%    0.38   0.0%    +1.34%
keltner_reversion      CL=F     45   75.6%   -1.26   0.0%   -14.97%   ⚠️ trap
williams_mean_rev      CL=F     39   56.4%   -0.03   0.0%    -0.14%
gap_fill               CL=F    236   55.5%    1.15   0.0%    +5.01%
```

Legend: **✅ shipped as preset**, **⚠️ excluded** (e.g. high WR but losing
money — the 25% losers were larger than winners).

---

## What ships as a preset

Curation rule: **WR ≥ 75% AND Sharpe > 0 AND total return > 0 AND ≥ 50 trades.**

| Preset ID | Strategy | Asset | WR | Sharpe | Return | Trades |
|---|---|---|---|---|---|---|
| `keltner_spy_d1` | Keltner Reversion | SPY | **80.0%** | 2.39 | +10.97% | 60 |
| `williams_spy_d1` | Williams %R | SPY | **77.7%** | 2.99 | +5.41% | 94 |
| `keltner_qqq_d1` | Keltner Reversion | QQQ | **79.2%** | 1.86 | +9.28% | 53 |
| `williams_qqq_d1` | Williams %R | QQQ | **77.9%** | 3.17 | +8.43% | 104 |

These four show up in the Slots tab's "Backtested presets" panel — one click
to instantiate as a disabled slot. They live in
[`backend/services/preset_slots.py`](../backend/services/preset_slots.py).

---

## What we deliberately **don't** ship — and why

* **`keltner_reversion` on CL=F** — 75.6% WR but **-15% return** over 15
  years. The 24% of losing trades had bigger losses than the 76% of winners
  had gains. Classic illustration of why WR alone is misleading.

* **`williams_mean_rev` BTC (92.9% WR)** — only 14 trades over 10 years.
  Statistically too thin to ship as a preset. Could be useful with looser
  thresholds or 1h timeframe.

* **TSLA pairs (max 67%)** — TSLA is too trendy / gappy for this style of
  mean reversion. Best result was `keltner_reversion` at 64% WR / +11%
  return — positive but below threshold.

* **Gold (`GC=F`) keltner / williams (72-73%)** — close miss on WR threshold,
  but positive returns. Worth revisiting with a tuned RSI threshold.

---

## Reproducing the report

```bash
# Inside the venv:
.venv/bin/python -m scripts.run_preset_bench
```

Outputs:
* `data/preset_bench.csv` — full 35-row report
* `data/preset_bench_winners.csv` — just the qualifying presets
* stdout — formatted table (mirrors the table above)

The script auto-backfills any asset with insufficient bars in the local
Parquet lake before backtesting.

---

## Adding a new preset

1. Add the strategy class under [`strategies/`](../strategies). Implement
   `analyze(df, current_position) -> Signal`. Follow the pattern in any of
   the existing five.
2. Register it in [`strategies/factory.py`](../strategies/factory.py) —
   `STRATEGY_DEFAULTS` entry + `get_strategy` branch.
3. Re-run `scripts/run_preset_bench.py`. Inspect the output.
4. If a (strategy × asset) pair clears the curation rule, copy the row from
   `preset_bench_winners.csv` into
   [`backend/services/preset_slots.py`](../backend/services/preset_slots.py)
   as a `PresetSlot(...)` entry.
5. Update this doc with the new row.
