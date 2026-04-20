"""Tauri sidecar entry point for the frozen PyInstaller build.

Tauri spawns this binary with ``--host 127.0.0.1 --port 8787``; we forward
to uvicorn with the app factory resolved from the packaged backend/ tree.
Works identically when run directly (``python scripts/sidecar_entry.py``)
for smoke testing before bundling.
"""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend-sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--reload", action="store_true", help="dev only")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper())

    # Deferred imports so --help is snappy and fatal failures
    # (missing uvicorn, bad backend import) surface clearly.
    import uvicorn

    # Import the app object directly. ``uvicorn.run("backend.main:app")``
    # goes through ``import_string`` which PyInstaller breaks; handing over
    # the object skips that path entirely. ``--reload`` in a frozen build is
    # meaningless, so we ignore it and fall back to reload=False.
    from backend.main import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
