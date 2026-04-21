"""Minimal migration runner.

Reads ``NNN_*.sql`` files in sort order, skips any already applied
(tracked via ``schema_version``), applies the rest in a transaction per
file. No downgrade path — this is v1 and we don't need one yet.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_migrations_dir() -> Path:
    """Locate the SQL migration files.

    In dev, ``__file__`` is a real path next to the .sql files. In a
    PyInstaller one-file bundle, the .sql files are extracted to
    ``_MEIPASS/backend/db/migrations/`` (via the spec's ``added_files``)
    and may live separately from the bundled bytecode, so we try that
    path too.
    """
    dev_path = Path(__file__).parent
    if any(dev_path.glob("*.sql")):
        return dev_path
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "backend" / "db" / "migrations"
        if any(frozen.glob("*.sql")):
            return frozen
    return dev_path  # fall back so the caller gets a clear "no migrations" error


_MIGRATIONS_DIR = _resolve_migrations_dir()


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    _ensure_version_table(conn)
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    return {int(row[0]) for row in rows}


def _discover_migrations() -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        stem = path.stem  # e.g. '001_initial'
        try:
            version = int(stem.split("_", 1)[0])
        except ValueError:
            continue
        out.append((version, path))
    return out


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply every pending migration in-order. Returns the list of newly-applied versions."""
    applied = _applied_versions(conn)
    newly_applied: list[int] = []
    for version, path in _discover_migrations():
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        logger.info("Applying migration %s", path.name)
        conn.executescript(sql)
        # Each migration file ends with an INSERT OR IGNORE into schema_version,
        # but tag it again here defensively in case a future migration forgets.
        conn.execute("INSERT OR IGNORE INTO schema_version(version) VALUES (?)", (version,))
        conn.commit()
        newly_applied.append(version)
    return newly_applied
