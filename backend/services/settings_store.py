"""SettingsStore — JSON-file-backed app settings.

Kept *outside* ``app.db`` on purpose: survives schema migrations cleanly,
human-inspectable, easy to export. Thread-safe via a file lock during
writes (last-writer-wins; fine for a single-user desktop app).
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data") / "settings.json"


@dataclass
class Settings:
    # Exchange
    testnet: bool = True

    # Notifications
    email_enabled: bool = False
    telegram_enabled: bool = False
    desktop_notifications: bool = True

    # Risk defaults
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.05
    confirm_above_usd: float = 1_000.0
    confirm_modify_pct: float = 0.10      # 10% change triggers a confirm modal
    confirm_leverage_above: int = 10
    aggregate_exposure_cap_usd: float = float("inf")

    # Data
    data_root: str = "data"
    backfill_throttle_ms: int = 0
    cross_validate_threshold_pct: float = 0.5
    duckdb_cache_mb: int = 512

    # Appearance
    theme: str = "dark"
    density: str = "comfortable"

    # Advanced
    dev_mode: bool = False
    log_level: str = "INFO"

    # Extras — any future key goes here until promoted
    extras: dict[str, Any] = field(default_factory=dict)


class SettingsStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self._lock = threading.RLock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("settings file corrupt, using defaults: %s", exc)
            return Settings()
        defaults = asdict(Settings())
        merged = {**defaults, **{k: v for k, v in raw.items() if k in defaults}}
        unknown = {k: v for k, v in raw.items() if k not in defaults}
        s = Settings(**merged)
        if unknown:
            s.extras.update(unknown)
        return s

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(asdict(self._settings), indent=2, default=_json_default))

    def all(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, patch: dict[str, Any]) -> Settings:
        defaults = asdict(Settings())
        with self._lock:
            current = asdict(self._settings)
            for k, v in patch.items():
                if k == "extras" and isinstance(v, dict):
                    current["extras"] = {**current.get("extras", {}), **v}
                elif k in defaults:
                    current[k] = v
                else:
                    current.setdefault("extras", {})[k] = v
            self._settings = Settings(**current)
            self.save()
            return self._settings


def _json_default(o: Any) -> Any:
    if o == float("inf"):
        return None
    raise TypeError(f"Not serialisable: {type(o)}")
