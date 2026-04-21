"""Tauri sidecar entry point for the frozen PyInstaller build.

Tauri spawns this binary with ``--host 127.0.0.1 --port 8787``; we forward
to uvicorn with the app factory resolved from the packaged backend/ tree.
Works identically when run directly (``python scripts/sidecar_entry.py``)
for smoke testing before bundling.

Boot logging: every launch appends one line to
``%LOCALAPPDATA%\\hyperliquid-bot\\logs\\boot.log`` BEFORE any heavy
import, and a stack trace if uvicorn itself fails. That file is the
single source of truth when users hit "the app is up but nothing works"
— the Tauri shell's stdout capture is invisible in release builds.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _user_log_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "hyperliquid-bot" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "hyperliquid-bot" / "logs"
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "hyperliquid-bot" / "logs"


def _boot_log(msg: str) -> None:
    """Append one line to boot.log — must never raise."""
    try:
        d = _user_log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "boot.log").open("a", encoding="utf-8") as fp:
            fp.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend-sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--reload", action="store_true", help="dev only")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    _boot_log(
        f"boot start host={args.host} port={args.port} "
        f"cwd={Path.cwd()} frozen={getattr(sys, 'frozen', False)} "
        f"meipass={getattr(sys, '_MEIPASS', None)} py={sys.version.split()[0]}"
    )

    logging.basicConfig(level=args.log_level.upper())

    try:
        # Deferred imports so --help is snappy and fatal failures
        # (missing uvicorn, bad backend import) surface clearly.
        import uvicorn

        # Import the app object directly. ``uvicorn.run("backend.main:app")``
        # goes through ``import_string`` which PyInstaller breaks; handing over
        # the object skips that path entirely.
        from backend.main import app

        _boot_log(f"backend.main imported — {len(app.routes)} routes registered")

        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            access_log=False,
        )
        _boot_log("uvicorn exited cleanly")
        return 0
    except BaseException as exc:  # noqa: BLE001
        _boot_log(f"FATAL {type(exc).__name__}: {exc}")
        _boot_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
