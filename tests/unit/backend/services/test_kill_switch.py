"""Tests for KillSwitchService — mocked exchange + real AppDB + AuditService."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.db.app_db import AppDB
from backend.services.audit import AuditService
from backend.services.kill_switch import KillSwitchService


@dataclass
class FakeExchange:
    cancelled: list[dict] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)
    closed_calls: list[tuple[str, str]] = field(default_factory=list)
    cancel_raises: bool = False
    close_raises_on: set[str] = field(default_factory=set)

    def cancel_all(self) -> list[dict[str, Any]]:
        if self.cancel_raises:
            raise RuntimeError("cancel_all down")
        return self.cancelled

    def get_all_positions(self) -> list[dict[str, Any]]:
        return list(self.positions)

    def close_position(self, symbol: str, dex: str = "") -> dict[str, Any]:
        self.closed_calls.append((symbol, dex))
        if symbol in self.close_raises_on:
            raise RuntimeError(f"close {symbol} failed")
        return {"status": "closed", "symbol": symbol}


@pytest.fixture
def harness():
    db = AppDB(":memory:")
    audit = AuditService(db)
    yield db, audit
    db.close()


def _seed_enabled_slots(db: AppDB, n: int) -> None:
    for i in range(n):
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO slots(id, kind, symbol, strategy, size_usd, enabled)
                VALUES (?, 'perp', 'BTC', 'ema_crossover', 100.0, 1)
                """,
                (f"s{i}",),
            )


class TestKillSwitchActivate:
    def test_happy_path_cascade(self, harness) -> None:
        db, audit = harness
        _seed_enabled_slots(db, 3)
        exchange = FakeExchange(
            cancelled=[{"oid": 1}, {"oid": 2}],
            positions=[{"symbol": "BTC"}, {"symbol": "ETH"}],
        )
        svc = KillSwitchService(exchange, db, audit)

        report = svc.activate(confirmation="KILL")
        assert len(report.orders_cancelled) == 2
        assert len(report.positions_closed) == 2
        assert report.slots_disabled == 3
        assert report.errors == []
        assert exchange.closed_calls == [("BTC", ""), ("ETH", "")]

        # State flipped to active.
        assert svc.is_active()
        assert svc.last_activated() is not None

        # All slots are now disabled.
        row = db.fetchone("SELECT COUNT(*) AS c FROM slots WHERE enabled = 1")
        assert row["c"] == 0

    def test_bad_confirmation_raises(self, harness) -> None:
        db, audit = harness
        svc = KillSwitchService(FakeExchange(), db, audit)
        with pytest.raises(ValueError):
            svc.activate(confirmation="please")

    def test_double_activation_is_noop(self, harness) -> None:
        db, audit = harness
        svc = KillSwitchService(FakeExchange(), db, audit)
        svc.activate(confirmation="KILL")
        assert svc.is_active()
        # Second activate returns an empty report, doesn't re-run the cascade.
        report = svc.activate(confirmation="KILL")
        assert report.orders_cancelled == []
        assert report.slots_disabled == 0

    def test_cancel_failure_captured_but_proceeds(self, harness) -> None:
        db, audit = harness
        _seed_enabled_slots(db, 1)
        exchange = FakeExchange(cancel_raises=True, positions=[{"symbol": "BTC"}])
        svc = KillSwitchService(exchange, db, audit)
        report = svc.activate(confirmation="KILL")
        # Cancel failed → captured in errors, but positions still closed and
        # slots still disabled.
        assert any(e["step"] == "cancel_all" for e in report.errors)
        assert len(report.positions_closed) == 1
        assert report.slots_disabled == 1

    def test_individual_close_failure_captured(self, harness) -> None:
        db, audit = harness
        exchange = FakeExchange(
            positions=[{"symbol": "BTC"}, {"symbol": "ETH"}],
            close_raises_on={"BTC"},
        )
        svc = KillSwitchService(exchange, db, audit)
        report = svc.activate(confirmation="KILL")
        # ETH still closed; BTC surfaced as an error.
        assert len(report.positions_closed) == 1
        assert any(e.get("symbol") == "BTC" for e in report.errors)

    def test_audit_rows_written(self, harness) -> None:
        db, audit = harness
        _seed_enabled_slots(db, 1)
        svc = KillSwitchService(FakeExchange(), db, audit)
        svc.activate(confirmation="KILL")
        events = audit.query()
        types = {e.event_type for e in events}
        assert "kill_switch_activated" in types
        assert "kill_switch_step" in types

    def test_callback_fires_with_report(self, harness) -> None:
        db, audit = harness
        received = []
        svc = KillSwitchService(
            FakeExchange(),
            db,
            audit,
            on_activated=[received.append],
        )
        svc.activate(confirmation="KILL")
        assert len(received) == 1


class TestKillSwitchReset:
    def test_reset_requires_resume_confirmation(self, harness) -> None:
        db, audit = harness
        svc = KillSwitchService(FakeExchange(), db, audit)
        svc.activate(confirmation="KILL")
        with pytest.raises(ValueError):
            svc.reset(confirmation="wrong")

    def test_reset_clears_active_state(self, harness) -> None:
        db, audit = harness
        svc = KillSwitchService(FakeExchange(), db, audit)
        svc.activate(confirmation="KILL")
        svc.reset(confirmation="RESUME")
        assert not svc.is_active()
