"""Tests for AppDB + initial migration."""
from __future__ import annotations

import sqlite3

import pytest

from backend.db.app_db import AppDB


@pytest.fixture
def db() -> AppDB:
    db = AppDB(":memory:")
    yield db
    db.close()


def test_migrate_applies_initial_schema(db: AppDB) -> None:
    assert db.schema_version() == 1
    for table in ("markets", "market_tags", "audit_log", "slots", "slot_state", "schema_version"):
        assert db.table_exists(table)


def test_migrate_is_idempotent() -> None:
    db = AppDB(":memory:")
    v1 = db.schema_version()
    # Re-apply migrations manually — should be no-op since already at latest.
    from backend.db.migrations.migrate import migrate

    newly = migrate(db.conn)
    assert newly == []
    assert db.schema_version() == v1


def test_audit_log_blocks_update(db: AppDB) -> None:
    db.execute(
        "INSERT INTO audit_log(event_type, source) VALUES ('x', 'test')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE audit_log SET event_type = 'y' WHERE id = 1")


def test_audit_log_blocks_delete(db: AppDB) -> None:
    db.execute(
        "INSERT INTO audit_log(event_type, source) VALUES ('x', 'test')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM audit_log")


def test_slot_foreign_key_cascades(db: AppDB) -> None:
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO slots(id, kind, symbol, strategy, size_usd, enabled)
            VALUES ('s1', 'perp', 'BTC', 'ema_crossover', 100.0, 1)
            """
        )
        conn.execute("INSERT INTO slot_state(slot_id) VALUES ('s1')")

    # Deleting the slot cascades to slot_state.
    with db.transaction() as conn:
        conn.execute("DELETE FROM slots WHERE id = 's1'")
    row = db.fetchone("SELECT COUNT(*) AS c FROM slot_state")
    assert row["c"] == 0


def test_transaction_rollback_on_error(db: AppDB) -> None:
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO slots(id, kind, symbol, strategy, size_usd) VALUES ('s_ok', 'perp', 'BTC', 'x', 100)"
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    row = db.fetchone("SELECT COUNT(*) AS c FROM slots")
    assert row["c"] == 0
