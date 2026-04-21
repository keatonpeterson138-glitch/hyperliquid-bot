"""Seed the credentials table on first boot.

Resolution order (first match wins, each skipped if it returns empty):

1. ``CREDENTIALS_SEED_FILE`` env var → explicit path to a JSON export blob
   (same shape as ``CredentialsStore.export_profile``).
2. ``<sys._MEIPASS>/backend/config/credentials_seed.json`` — bundled into
   the PyInstaller one-file sidecar.
3. ``<cwd>/backend/config/credentials_seed.json`` — local dev file (gitignored).
4. Per-provider env vars:
     * ``FRED_API_KEY``, ``ALPHAVANTAGE_API_KEY``, ``CRYPTOCOMPARE_API_KEY``,
       ``COINGECKO_API_KEY``, ``PLAID_CLIENT_ID`` + ``PLAID_SECRET``,
       ``ETRADE_CONSUMER_KEY`` + ``ETRADE_CONSUMER_SECRET``,
       ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHANNEL``.
   Last-resort so the user can set keys in the environment without touching
   files.

Seeding only runs when the ``credentials`` table is empty — we never
overwrite user-entered keys. The user's Settings "Export profile" → save
the resulting JSON as the seed file to bake it into the next installer.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from backend.services.credentials_store import CredentialsStore

logger = logging.getLogger(__name__)


def _bundle_root() -> Path | None:
    """PyInstaller one-file builds extract to ``sys._MEIPASS``. In dev we
    fall back to the repo root so the seed file works both for a frozen
    sidecar and ``python -m backend.main``."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return None


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    env_path = os.environ.get("CREDENTIALS_SEED_FILE")
    if env_path:
        out.append(Path(env_path))

    bundle = _bundle_root()
    if bundle is not None:
        out.append(bundle / "backend" / "config" / "credentials_seed.json")

    out.append(Path.cwd() / "backend" / "config" / "credentials_seed.json")
    return out


def _load_seed_file() -> dict[str, Any] | None:
    for path in _candidate_paths():
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as fp:
                    blob = json.load(fp)
                if isinstance(blob, dict) and isinstance(blob.get("credentials"), list):
                    logger.info("credentials seed: loading from %s", path)
                    return blob
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("credentials seed: could not read %s: %s", path, exc)
    return None


def _env_seed() -> dict[str, Any] | None:
    """Fallback: scrape per-provider env vars. Only provides basic entries;
    if you need more nuance, use the JSON seed file."""
    creds: list[dict[str, Any]] = []

    def add(provider: str, api_key: str | None, api_secret: str | None = None,
            metadata: dict[str, Any] | None = None, label: str = "default") -> None:
        if not api_key:
            return
        entry: dict[str, Any] = {
            "provider": provider,
            "label": label,
            "api_key": api_key,
        }
        if api_secret:
            entry["api_secret"] = api_secret
        if metadata:
            entry["metadata"] = metadata
        creds.append(entry)

    add("fred",          os.environ.get("FRED_API_KEY"))
    add("alpha_vantage", os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY"))
    add("cryptocompare", os.environ.get("CRYPTOCOMPARE_API_KEY"))
    add("coingecko",     os.environ.get("COINGECKO_API_KEY"))
    add("plaid",
        os.environ.get("PLAID_CLIENT_ID"),
        os.environ.get("PLAID_SECRET"),
        {"environment": os.environ.get("PLAID_ENV", "sandbox")})
    add("etrade",
        os.environ.get("ETRADE_CONSUMER_KEY"),
        os.environ.get("ETRADE_CONSUMER_SECRET"),
        {"sandbox": os.environ.get("ETRADE_SANDBOX", "false").lower() in {"1", "true", "yes"}})
    add("telegram",
        os.environ.get("TELEGRAM_BOT_TOKEN"),
        metadata={"channel": os.environ.get("TELEGRAM_CHANNEL")} if os.environ.get("TELEGRAM_CHANNEL") else None)

    if not creds:
        return None
    return {"version": 1, "credentials": creds}


def seed_if_empty(store: CredentialsStore) -> dict[str, int]:
    """Import defaults if (and only if) the credentials table is empty.

    Returns the import stats so callers can log what happened. Never
    raises — seed failures are logged and swallowed so a malformed file
    doesn't wedge boot.
    """
    try:
        existing = store.list()
    except Exception as exc:  # noqa: BLE001
        logger.warning("credentials seed: could not list existing creds: %s", exc)
        return {"created": 0, "updated": 0, "skipped": 0}

    if existing:
        return {"created": 0, "updated": 0, "skipped": len(existing)}

    blob = _load_seed_file() or _env_seed()
    if blob is None:
        logger.info("credentials seed: no seed source found — table stays empty")
        return {"created": 0, "updated": 0, "skipped": 0}

    try:
        result = store.import_profile(blob, replace=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("credentials seed: import failed: %s", exc)
        return {"created": 0, "updated": 0, "skipped": 0}

    logger.info("credentials seed: created=%s updated=%s skipped=%s",
                result.get("created"), result.get("updated"), result.get("skipped"))
    return result
