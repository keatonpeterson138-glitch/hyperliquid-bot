"""/logs — read recent backend log lines.

The backend writes a tail-friendly rotating log at ``data/logs/backend.log``.
The UI's log viewer polls this endpoint with ``?tail=N&level=WARN`` to
show recent events without shipping the full log to the wire on every
keystroke.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.services.settings_store import SettingsStore

router = APIRouter(tags=["logs"])

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def get_log_path() -> Path:
    # Default path; tests override.
    return Path("data") / "logs" / "backend.log"


def get_settings() -> SettingsStore | None:
    # Defaults to None — tests inject a store if they want level filtering.
    return None


LogPathDep = Annotated[Path, Depends(get_log_path)]


@router.get("/logs")
def tail_logs(
    path: LogPathDep,
    tail: Annotated[int, Query(ge=1, le=5000)] = 200,
    level: str | None = None,
) -> dict:
    if level is not None and level.upper() not in LEVELS:
        raise HTTPException(status_code=400, detail=f"bad level: {level}")
    level_set = _levels_at_or_above(level.upper()) if level else None

    if not path.exists():
        return {"path": str(path), "lines": []}

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"log read failed: {exc}") from exc

    if level_set is not None:
        lines = [ln for ln in lines if _level_of(ln) in level_set]

    out = lines[-tail:]
    return {"path": str(path), "lines": [ln.rstrip("\n") for ln in out]}


def _levels_at_or_above(floor: str) -> set[str]:
    idx = LEVELS.index(floor)
    return set(LEVELS[idx:])


def _level_of(line: str) -> str | None:
    for lvl in LEVELS:
        if lvl in line:
            return lvl
    return None


def configure_file_logging(path: Path | str | None = None) -> Path:
    """Attach a rotating file handler to the root logger. Called once at
    backend startup (from ``backend/main.py`` lifespan).
    """
    from logging.handlers import RotatingFileHandler

    log_path = Path(path) if path is not None else Path("data") / "logs" / "backend.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    # Avoid duplicate handlers on --reload.
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_path):
            root.removeHandler(h)
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    return log_path
