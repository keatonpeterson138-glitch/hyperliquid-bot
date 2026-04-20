"""Thin SQLite connection + helpers for the app-state database.

SQLAlchemy is overkill here — we're a single-process, local-only app.
Stick with stdlib ``sqlite3`` and inline SQL. Every long-lived service
(UniverseManager, AuditService, TradeEngineService) takes an ``AppDB``
in its constructor and calls the typed helpers below.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.db.migrations.migrate import migrate

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: Path = Path("data") / "app.db"


class AppDB:
    """Serialized SQLite wrapper.

    SQLite with WAL mode permits concurrent readers but only one writer
    at a time — we enforce a module-level RLock for writes to avoid
    ``database is locked`` under contention. Tests use ``":memory:"``.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = str(path if path is not None else DEFAULT_DB_PATH)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.path,
            isolation_level=None,  # autocommit; we manage transactions explicitly
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._write_lock = threading.RLock()
        migrate(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    # ── Query helpers ──────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def fetchone(
        self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()
    ) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def fetchall(
        self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()
    ) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params).fetchall())

    @contextmanager
    def transaction(self):
        """Context manager for a write transaction serialized by the module lock."""
        with self._write_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # ── Introspection ──────────────────────────────────────────────────────

    def schema_version(self) -> int | None:
        row = self.fetchone("SELECT MAX(version) AS v FROM schema_version")
        if row is None or row["v"] is None:
            return None
        return int(row["v"])

    def table_exists(self, name: str) -> bool:
        row = self.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return row is not None
