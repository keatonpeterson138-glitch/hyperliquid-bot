"""Tests for SlotRepository CRUD + slot_state upsert."""
from __future__ import annotations

import pytest

from backend.db.app_db import AppDB
from backend.models.slot import Slot
from backend.services.slot_repository import SlotRepository


@pytest.fixture
def repo() -> SlotRepository:
    db = AppDB(":memory:")
    yield SlotRepository(db)
    db.close()


def _new_slot(**overrides) -> Slot:
    defaults = dict(
        id="",
        kind="perp",
        symbol="BTC",
        strategy="ema_crossover",
        size_usd=100.0,
        interval="1h",
        strategy_params={"fast_period": 9, "slow_period": 21},
        leverage=3,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        enabled=False,
    )
    defaults.update(overrides)
    return Slot(**defaults)


class TestSlotCRUD:
    def test_create_assigns_id_when_blank(self, repo) -> None:
        slot = repo.create(_new_slot())
        assert slot.id.startswith("slot_")
        fetched = repo.get(slot.id)
        assert fetched is not None
        assert fetched.symbol == "BTC"

    def test_create_preserves_explicit_id(self, repo) -> None:
        slot = repo.create(_new_slot(id="slot_explicit"))
        assert slot.id == "slot_explicit"

    def test_strategy_params_round_trip(self, repo) -> None:
        slot = repo.create(_new_slot(strategy_params={"k": 7}))
        fetched = repo.get(slot.id)
        assert fetched.strategy_params == {"k": 7}

    def test_list_filters_enabled_only(self, repo) -> None:
        repo.create(_new_slot(enabled=True))
        repo.create(_new_slot(enabled=False))
        repo.create(_new_slot(enabled=True))
        all_slots = repo.list_all()
        enabled = repo.list_all(enabled_only=True)
        assert len(all_slots) == 3
        assert len(enabled) == 2
        assert all(s.enabled for s in enabled)

    def test_update_partial_fields(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.update(slot.id, {"size_usd": 250.0, "enabled": True})
        fetched = repo.get(slot.id)
        assert fetched.size_usd == 250.0
        assert fetched.enabled is True

    def test_update_strategy_params_serialize(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.update(slot.id, {"strategy_params": {"new": "params"}})
        fetched = repo.get(slot.id)
        assert fetched.strategy_params == {"new": "params"}

    def test_delete_removes(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.delete(slot.id)
        assert repo.get(slot.id) is None


class TestSlotState:
    def test_upsert_creates_then_updates(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.upsert_state(slot.id, current_position="LONG", entry_price=100.0)
        s1 = repo.get_state(slot.id)
        assert s1.current_position == "LONG"
        assert s1.entry_price == 100.0

        repo.upsert_state(slot.id, current_position=None, entry_price=None)
        s2 = repo.get_state(slot.id)
        assert s2.current_position is None
        assert s2.entry_price is None

    def test_upsert_preserves_unspecified_fields(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.upsert_state(slot.id, current_position="LONG", entry_price=100.0)
        # Update last_signal only — current_position should remain "LONG".
        repo.upsert_state(slot.id, last_signal="bullish")
        state = repo.get_state(slot.id)
        assert state.current_position == "LONG"
        assert state.last_signal == "bullish"

    def test_open_order_ids_round_trip(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.upsert_state(slot.id, open_order_ids=["abc", "def"])
        state = repo.get_state(slot.id)
        assert state.open_order_ids == ["abc", "def"]

    def test_state_cascades_on_slot_delete(self, repo) -> None:
        slot = repo.create(_new_slot())
        repo.upsert_state(slot.id, current_position="LONG")
        repo.delete(slot.id)
        assert repo.get_state(slot.id) is None
