"""PlaidStore — items + accounts round-trip."""
from __future__ import annotations

import pytest

from backend.db.app_db import AppDB
from backend.services.plaid_store import PlaidStore


@pytest.fixture
def store() -> PlaidStore:
    db = AppDB(":memory:")
    yield PlaidStore(db)
    db.close()


def test_add_and_fetch_item(store: PlaidStore) -> None:
    item = store.add_item(
        plaid_item_id="plaid_item_abc",
        access_token="acc_tok_xyz",
        institution_id="ins_1",
        institution_name="Chase",
        environment="production",
    )
    assert item.id.startswith("pli_")
    assert item.institution_name == "Chase"
    assert item.environment == "production"

    fetched = store.get_item(item.id)
    assert fetched is not None
    assert fetched.access_token == "acc_tok_xyz"


def test_add_item_upserts_on_plaid_item_id(store: PlaidStore) -> None:
    first = store.add_item(plaid_item_id="reuse_id", access_token="OLD")
    second = store.add_item(plaid_item_id="reuse_id", access_token="NEW", institution_name="Fidelity")
    assert first.id == second.id
    refetched = store.get_item(first.id)
    assert refetched is not None
    assert refetched.access_token == "NEW"
    assert refetched.institution_name == "Fidelity"


def test_upsert_account_updates_existing(store: PlaidStore) -> None:
    item = store.add_item(plaid_item_id="I1", access_token="T1", institution_name="Fidelity")
    a = store.upsert_account(
        item_id=item.id, plaid_account_id="acc1",
        name="401k", subtype="401k", broker_label="fidelity", tracked=True,
    )
    assert a.broker_label == "fidelity"
    assert a.tracked is True

    # Upsert again with different flags.
    b = store.upsert_account(
        item_id=item.id, plaid_account_id="acc1",
        name="401k-renamed", subtype="401k", tracked=False,
    )
    assert a.id == b.id
    assert b.name == "401k-renamed"
    assert b.tracked is False
    # broker_label is preserved via COALESCE when omitted in the update.
    assert b.broker_label == "fidelity"


def test_list_tracked_filters_out_untracked(store: PlaidStore) -> None:
    item = store.add_item(plaid_item_id="I", access_token="T")
    store.upsert_account(item_id=item.id, plaid_account_id="a1", tracked=True,  broker_label="other")
    store.upsert_account(item_id=item.id, plaid_account_id="a2", tracked=False, broker_label="other")
    tracked = store.list_tracked_accounts()
    assert [a.plaid_account_id for a in tracked] == ["a1"]


def test_delete_item_cascades_accounts(store: PlaidStore) -> None:
    item = store.add_item(plaid_item_id="I", access_token="T")
    store.upsert_account(item_id=item.id, plaid_account_id="a1")
    store.upsert_account(item_id=item.id, plaid_account_id="a2")
    assert len(store.list_accounts()) == 2

    store.delete_item(item.id)
    # FK cascade wipes the accounts too.
    assert store.list_accounts() == []


def test_set_tracked_and_set_broker_label(store: PlaidStore) -> None:
    item = store.add_item(plaid_item_id="I", access_token="T")
    acc = store.upsert_account(item_id=item.id, plaid_account_id="a1",
                                broker_label="other", tracked=True)
    updated = store.set_tracked(acc.id, False)
    assert updated is not None and updated.tracked is False

    relabeled = store.set_broker_label(acc.id, "robinhood")
    assert relabeled is not None and relabeled.broker_label == "robinhood"
