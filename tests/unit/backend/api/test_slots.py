"""API tests for /slots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api import slots as slots_api
from backend.db.app_db import AppDB
from backend.main import create_app
from backend.services.audit import AuditService
from backend.services.kill_switch import KillSwitchService
from backend.services.order_executor import OrderExecutor
from backend.services.slot_repository import SlotRepository
from backend.services.slot_runner import SlotRunner
from backend.services.trade_engine_service import TradeEngineService
from strategies.base import BaseStrategy, Signal, SignalType


class _Strategy(BaseStrategy):
    def __init__(self):
        super().__init__("test")

    def analyze(self, df, current_position=None):  # noqa: ARG002
        return Signal(SignalType.LONG, 1.0, "test")


@dataclass
class FakeExchange:
    place_calls: list = field(default_factory=list)

    def get_market_price(self, s):  # noqa: ARG002
        return 100.0

    def place_market_order(self, symbol, is_buy, size_usd, leverage):
        self.place_calls.append((symbol, is_buy, size_usd, leverage))
        return {"order_id": "o1", "fill_price": 100.0}

    def close_position(self, symbol, dex=""):
        return {"status": "closed"}

    def cancel_all(self):
        return []

    def get_all_positions(self):
        return []


@pytest.fixture
def harness():
    db = AppDB(":memory:")
    repo = SlotRepository(db)
    audit = AuditService(db)
    exchange = FakeExchange()
    runner = SlotRunner(
        repo=repo,
        audit=audit,
        exchange=exchange,
        candle_query=lambda *a, **kw: pd.DataFrame(
            {
                "open": [100.0] * 50,
                "high": [101.0] * 50,
                "low": [99.0] * 50,
                "close": [100.0] * 50,
                "volume": [1000.0] * 50,
            },
            index=pd.to_datetime(
                [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(50)],
                utc=True,
            ),
        ),
        strategy_factory=lambda *a, **kw: _Strategy(),
        executor=OrderExecutor(),
    )
    kill = KillSwitchService(exchange, db, audit)
    engine = TradeEngineService(repo, runner, kill_switch=kill)
    app = create_app()
    app.dependency_overrides[slots_api.get_slot_repo] = lambda: repo
    app.dependency_overrides[slots_api.get_trade_engine] = lambda: engine
    yield TestClient(app), repo, exchange
    db.close()


def _slot_payload(**overrides):
    defaults = dict(
        kind="perp",
        symbol="BTC",
        strategy="ema_crossover",
        size_usd=100.0,
        interval="1h",
        leverage=3,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        enabled=False,
    )
    defaults.update(overrides)
    return defaults


class TestSlotsAPI:
    def test_create_then_list(self, harness) -> None:
        client, _, _ = harness
        resp = client.post("/slots", json=_slot_payload())
        assert resp.status_code == 200
        slot_id = resp.json()["id"]

        resp = client.get("/slots")
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()]
        assert slot_id in ids

    def test_get_unknown_404(self, harness) -> None:
        client, _, _ = harness
        resp = client.get("/slots/nonexistent")
        assert resp.status_code == 404

    def test_patch_updates_fields(self, harness) -> None:
        client, _, _ = harness
        slot_id = client.post("/slots", json=_slot_payload()).json()["id"]
        resp = client.patch(f"/slots/{slot_id}", json={"size_usd": 250.0})
        assert resp.status_code == 200
        assert resp.json()["size_usd"] == 250.0

    def test_delete(self, harness) -> None:
        client, _, _ = harness
        slot_id = client.post("/slots", json=_slot_payload()).json()["id"]
        resp = client.delete(f"/slots/{slot_id}")
        assert resp.status_code == 204
        assert client.get(f"/slots/{slot_id}").status_code == 404

    def test_start_then_stop(self, harness) -> None:
        client, _, _ = harness
        slot_id = client.post("/slots", json=_slot_payload()).json()["id"]
        resp = client.post(f"/slots/{slot_id}/start")
        assert resp.json()["enabled"] is True
        resp = client.post(f"/slots/{slot_id}/stop")
        assert resp.json()["enabled"] is False

    def test_stop_all(self, harness) -> None:
        client, _, _ = harness
        for _ in range(3):
            slot_id = client.post("/slots", json=_slot_payload()).json()["id"]
            client.post(f"/slots/{slot_id}/start")
        resp = client.post("/slots/stop-all")
        assert resp.json()["slots_stopped"] == 3

    def test_tick_returns_decision(self, harness) -> None:
        client, _, _ = harness
        slot_id = client.post("/slots", json=_slot_payload()).json()["id"]
        client.post(f"/slots/{slot_id}/start")
        resp = client.post(f"/slots/{slot_id}/tick")
        body = resp.json()
        assert body["action"] in ("open_long", "open_short", "hold")
