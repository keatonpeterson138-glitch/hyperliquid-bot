# build_windows.ps1 — produce a Hyperliquid Bot Windows installer locally.
#
# Prerequisites (install once, in any order):
#   1. Python 3.12 (any 3.12.x is fine):  https://www.python.org/downloads/windows/
#      → check "Add python.exe to PATH" during install.
#   2. Node.js 20 LTS:                    https://nodejs.org/en/download
#   3. Rust (MSVC toolchain):             https://rustup.rs/
#      → run the installer and accept defaults; a VS 2022 Build Tools prompt
#        will appear if you're missing the C++ toolchain — let it install.
#   4. WebView2 runtime is already on every Windows 11 machine; nothing to do.
#
# Then, from a fresh PowerShell in the repo root:
#   .\scripts\build_windows.ps1
#
# Output lands at:
#   ui\src-tauri\target\release\bundle\msi\Hyperliquid Bot_<ver>_x64_en-US.msi
#   ui\src-tauri\target\release\bundle\nsis\Hyperliquid Bot_<ver>_x64-setup.exe

$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

function Require-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name not found in PATH — see prerequisites in scripts/build_windows.ps1"
    }
}

Write-Host "▶ Checking prerequisites..." -ForegroundColor Cyan
Require-Cmd python
Require-Cmd node
Require-Cmd npm
Require-Cmd cargo
Require-Cmd rustc

# ── 1. Python backend sidecar ─────────────────────────────────────
Write-Host "▶ Building Python backend sidecar via PyInstaller..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel setuptools | Out-Null
pip install -r requirements.txt | Out-Null
pip install pyinstaller | Out-Null
pyinstaller --clean --noconfirm backend-sidecar.spec
deactivate

$triple = "x86_64-pc-windows-msvc"
$sidecarDir = "ui\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $sidecarDir | Out-Null
$dest = "$sidecarDir\backend-sidecar-$triple.exe"
Copy-Item -Path "dist\backend-sidecar.exe" -Destination $dest -Force
Write-Host "  wrote $dest" -ForegroundColor DarkGray

# ── 2. Tauri bundle ───────────────────────────────────────────────
Write-Host "▶ Installing UI dependencies..." -ForegroundColor Cyan
Push-Location ui
npm install | Out-Null

Write-Host "▶ Building Tauri installer (this takes ~10 min on a clean cache)..." -ForegroundColor Cyan
npm run tauri:build

Pop-Location

# ── 3. Report artefacts ───────────────────────────────────────────
Write-Host "▶ Installer artefacts:" -ForegroundColor Green
Get-ChildItem -Recurse ui\src-tauri\target\release\bundle |
    Where-Object { $_.Extension -in ".msi", ".exe" } |
    Select-Object FullName, @{ N = "MB"; E = { [math]::Round($_.Length / 1MB, 2) } } |
    Format-Table
