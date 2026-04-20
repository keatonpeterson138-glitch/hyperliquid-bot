"""Tests for bootstrap_lake CLI."""
from __future__ import annotations

from datetime import UTC, datetime

from backend.db.app_db import AppDB
from backend.services.universe_manager import UniverseManager
from backend.tools import bootstrap_lake as bl


class _FakeInfo:
    def meta(self, dex: str = "") -> dict:
        if dex == "":
            return {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]}
        return {"universe": []}


def _rig():
    db = AppDB(":memory:")
    um = UniverseManager(db, info=_FakeInfo(), hip3_dexes=())
    um.refresh()
    bl.ensure_progress_table(db)
    return db, um


def test_ensure_progress_table_idempotent() -> None:
    db = AppDB(":memory:")
    bl.ensure_progress_table(db)
    bl.ensure_progress_table(db)
    assert db.table_exists("bootstrap_progress")


def test_plan_produces_symbol_x_interval() -> None:
    db, um = _rig()
    plan = bl.plan(um, intervals=("1d", "1h"), max_symbols=2)
    # 2 symbols × 2 intervals
    assert len(plan) == 4


def test_run_one_marks_slices_complete() -> None:
    db, um = _rig()
    item = bl.BootstrapPlanItem(
        symbol="BTC", interval="1h",
        from_ts=datetime(2023, 6, 1, tzinfo=UTC),
        to_ts=datetime(2024, 2, 1, tzinfo=UTC),
    )
    calls: list[tuple] = []

    def fake_backfill(*, symbol, interval, from_ts, to_ts):
        calls.append((symbol, interval, from_ts, to_ts))
        return {"bars_written": 42}

    result = bl.run_one(item, db, backfill_fn=fake_backfill)
    # spans 2023 + 2024 — 2 yearly slices
    assert len(calls) == 2
    assert result["total_bars"] == 84
    done = bl.completed_slices(db)
    assert ("BTC", "1h", 2023) in done
    assert ("BTC", "1h", 2024) in done


def test_run_one_resumes_on_reentry() -> None:
    db, um = _rig()
    item = bl.BootstrapPlanItem(
        symbol="ETH", interval="1d",
        from_ts=datetime(2023, 1, 1, tzinfo=UTC),
        to_ts=datetime(2024, 12, 31, tzinfo=UTC),
    )
    calls: list[tuple] = []

    def fake_backfill(**kw):
        calls.append(kw)
        return {"bars_written": 10}

    bl.run_one(item, db, backfill_fn=fake_backfill)
    assert len(calls) == 2  # 2 years
    # Rerun — should skip everything.
    bl.run_one(item, db, backfill_fn=fake_backfill)
    assert len(calls) == 2


def test_run_one_records_failures() -> None:
    db, um = _rig()
    item = bl.BootstrapPlanItem(
        symbol="SOL", interval="1d",
        from_ts=datetime(2024, 1, 1, tzinfo=UTC),
        to_ts=datetime(2024, 6, 1, tzinfo=UTC),
    )

    def failing(**_):
        raise RuntimeError("api limit")

    r = bl.run_one(item, db, backfill_fn=failing)
    assert r["total_bars"] == 0
    # Failed slice not in completed set
    assert ("SOL", "1d", 2024) not in bl.completed_slices(db)
    # But row was written with status=failed
    row = db.fetchone("SELECT status, error FROM bootstrap_progress WHERE symbol=? AND interval=? AND year=?",
                      ("SOL", "1d", 2024))
    assert row["status"] == "failed"
    assert "api limit" in row["error"]


def test_run_summary_shape() -> None:
    db, um = _rig()
    items = bl.plan(um, intervals=("1d",), max_symbols=2)
    result = bl.run(items, db, backfill_fn=lambda **_: {"bars_written": 5})
    assert result["plan_size"] == 2
    assert len(result["results"]) == 2
