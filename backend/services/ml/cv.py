"""Purged k-fold + embargo cross-validation (Prado AFML ch. 7).

Financial data is non-IID. Standard k-fold leaks because:
  (a) training rows whose label-horizon overlaps the test set infer
      future information,
  (b) training rows immediately adjacent to the test boundary learn
      serial-correlated patterns that inflate test metrics.

Purging removes (a). Embargo removes (b). Both are essential — naive
k-fold on financial data routinely produces Sharpe ratios that
evaporate in live trading.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PurgedKFold:
    n_splits: int = 5
    label_horizon: int = 1    # bars of look-ahead in the label
    embargo_bars: int = 0     # train rows within ``embargo_bars`` of test are dropped

    def split(self, index: pd.Index) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        n = len(index)
        if self.n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if self.n_splits > n:
            raise ValueError("n_splits larger than n")

        fold_size = n // self.n_splits
        for k in range(self.n_splits):
            test_start = k * fold_size
            test_end = n if k == self.n_splits - 1 else test_start + fold_size
            test = np.arange(test_start, test_end)

            # Purge — drop any train index whose label horizon overlaps [test_start, test_end).
            purged_upper = test_start - self.label_horizon
            # Embargo — extend the test boundary forward by embargo_bars.
            embargo_upper = test_end + self.embargo_bars
            train_mask = np.ones(n, dtype=bool)
            train_mask[test] = False
            # Kill anything in the purged + embargo zone.
            train_mask[max(0, purged_upper): min(n, embargo_upper)] = False
            train = np.where(train_mask)[0]
            yield train, test
