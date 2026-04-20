"""Tests for NotesStore + WalletService."""
from __future__ import annotations

import pytest

from backend.db.app_db import AppDB
from backend.services.audit import AuditService
from backend.services.notes_store import NotesStore
from backend.services.order_repository import OrderRepository
from backend.services.wallet import WalletService


@pytest.fixture
def notes_rig():
    db = AppDB(":memory:")
    yield NotesStore(db)
    db.close()


@pytest.fixture
def wallet_rig():
    db = AppDB(":memory:")
    orders = OrderRepository(db)
    audit = AuditService(db)
    svc = WalletService(orders, audit)
    yield svc, orders, audit
    db.close()


# ── Notes ──────────────────────────────────────────────────────────


def test_notes_crud(notes_rig) -> None:
    store = notes_rig
    n = store.create(title="Hypothesis", body_md="# idea", tags=["btc", "regime"])
    assert n.id.startswith("note_")
    assert n.tags == ["btc", "regime"]

    fetched = store.get(n.id)
    assert fetched is not None and fetched.title == "Hypothesis"

    updated = store.update(n.id, {"title": "Revised", "body_md": "# updated"})
    assert updated.title == "Revised"
    assert updated.body_md == "# updated"

    store.delete(n.id)
    assert store.get(n.id) is None


def test_notes_list_filter_by_tag(notes_rig) -> None:
    store = notes_rig
    store.create(title="a", tags=["btc"])
    store.create(title="b", tags=["eth"])
    store.create(title="c", tags=["btc", "regime"])
    btc = store.list(tag="btc")
    assert len(btc) == 2


def test_notes_attachment(notes_rig) -> None:
    store = notes_rig
    n = store.create(title="x")
    store.add_attachment(n.id, path="data/notes/x/shot1.png", kind="screenshot")
    refreshed = store.get(n.id)
    assert refreshed and len(refreshed.attachments) == 1
    assert refreshed.attachments[0].kind == "screenshot"


def test_notes_reject_bad_kind(notes_rig) -> None:
    store = notes_rig
    n = store.create(title="x")
    with pytest.raises(ValueError):
        store.add_attachment(n.id, path="x", kind="bogus")


# ── Wallet ─────────────────────────────────────────────────────────


def test_wallet_summary_empty(wallet_rig) -> None:
    svc, _, _ = wallet_rig
    s = svc.summary()
    assert s.total_notional_usd == 0.0
    assert s.open_orders == 0
    assert s.positions == []


def test_wallet_summary_falls_back_to_orders(wallet_rig) -> None:
    svc, orders, _ = wallet_rig
    o = orders.create(symbol="BTC", side="long", size_usd=150, entry_type="market")
    orders.update_status(o.id, "working")
    s = svc.summary()
    assert len(s.positions) == 1
    assert s.positions[0].symbol == "BTC"
    assert s.total_notional_usd == 150.0
    assert s.open_orders == 1


class _FakeProvider:
    def get_balance(self):
        return {"usdc": 5_000.5}

    def get_all_positions(self):
        return [
            {"symbol": "BTC", "side": "long", "size_usd": 100, "entry_price": 60_000, "unrealised_pnl_usd": 10},
            {"symbol": "ETH", "side": "short", "size_usd": 50, "entry_price": 3_000, "unrealised_pnl_usd": -5},
        ]


def test_wallet_summary_uses_provider(wallet_rig) -> None:
    svc, _, _ = wallet_rig
    svc.balance_provider = _FakeProvider()
    s = svc.summary(wallet_address="0xabc")
    assert s.usdc_balance == 5_000.5
    assert s.wallet_address == "0xabc"
    assert s.total_notional_usd == 150
    assert abs(s.unrealised_pnl_usd - 5) < 1e-9


def test_wallet_recent_activity_limit(wallet_rig) -> None:
    svc, orders, _ = wallet_rig
    for i in range(5):
        orders.create(symbol=f"SYM{i}", side="long", size_usd=10, entry_type="market")
    recent = svc.recent_activity(3)
    assert len(recent) == 3
