# PyInstaller spec for the Tauri Python sidecar.
#
# Produces a single-file executable that:
#   1. Launches uvicorn on host/port given via argv (defaults 127.0.0.1:8787).
#   2. Packages FastAPI, uvicorn, pandas, pyarrow, duckdb, keyring, and the
#      full ``backend/`` + ``strategies/`` + ``core/`` trees plus ``engine.py``.
#   3. Ships as ``backend-sidecar`` (Linux/macOS) or ``backend-sidecar.exe``
#      (Windows) — Tauri's ``externalBin`` triple-suffixing re-hashes the
#      name to ``backend-sidecar-<target-triple>`` at bundle time.
#
# Build:   pyinstaller --clean backend-sidecar.spec
# Outputs: dist/backend-sidecar(.exe)
# Then rename to match the target triple and drop into ui/src-tauri/binaries/
# before ``npm run tauri:build``.

# ruff: noqa
# mypy: ignore-errors

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
PROJECT = Path.cwd()

hiddenimports = [
    *collect_submodules("backend"),
    *collect_submodules("strategies"),
    *collect_submodules("core"),
    "engine",
    *collect_submodules("uvicorn"),
    *collect_submodules("fastapi"),
    *collect_submodules("starlette"),
    *collect_submodules("pydantic"),
    *collect_submodules("pydantic_core"),
    *collect_submodules("pandas"),
    *collect_submodules("pyarrow"),
    "duckdb",
    "numpy",
    "httpx",
    "keyring",
    "keyring.backends",
    "keyring.backends.SecretService",
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.chainer",
    "cryptography",
    *collect_submodules("hyperliquid"),
    "sklearn",
    "sklearn.linear_model",
    "sklearn.pipeline",
    "sklearn.preprocessing",
    "sklearn.metrics",
    "joblib",
]

added_files = [
    (str(PROJECT / "backend" / "db" / "migrations"), "backend/db/migrations"),
]
for pkg in ("fastapi", "pydantic", "pydantic_core", "duckdb"):
    try:
        added_files.extend(collect_data_files(pkg))
    except Exception:
        pass

a = Analysis(
    ["scripts/sidecar_entry.py"],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=added_files,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "tkinter",
        "yfinance",
        "xgboost",
        "scipy.io.matlab",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="backend-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
