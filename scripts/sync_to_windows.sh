#!/usr/bin/env bash
# sync_to_windows.sh — mirror this WSL repo to /mnt/c/Projects/hyperliquid-bot/
# so you can run the Windows-native Tauri + PyInstaller build from that side.
#
# Mirrors the same pattern used for structdraft. Safe to re-run — rsync
# does an incremental diff with --delete so the Windows copy stays a
# bit-for-bit mirror of the WSL working tree (minus build artifacts).
#
# Usage:
#   ./scripts/sync_to_windows.sh                    # sync only
#   ./scripts/sync_to_windows.sh --dry-run          # preview the diff
#   ./scripts/sync_to_windows.sh --build            # sync + kick off the
#                                                   # Windows PS build
#
# Output on Windows:
#   C:\Projects\hyperliquid-bot\ui\src-tauri\target\release\bundle\msi\*.msi
#   C:\Projects\hyperliquid-bot\ui\src-tauri\target\release\bundle\nsis\*.exe

set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="/mnt/c/Projects/hyperliquid-bot/"
DRY_RUN=0
DO_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --build) DO_BUILD=1 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$DEST"

# Excludes — anything build-generated or platform-specific.
EXCLUDES=(
  --exclude='.git/objects/pack/'
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='.pytest_cache/'
  --exclude='.ruff_cache/'
  --exclude='build/'
  --exclude='dist/'
  --exclude='node_modules/'
  --exclude='ui/src-tauri/target/'
  --exclude='ui/src-tauri/binaries/backend-sidecar-*'
  --exclude='data/'
  --exclude='.claude/'
  --exclude='*.pyc'
  --exclude='.DS_Store'
)

echo "▶ Syncing $SRC → $DEST"
if [[ $DRY_RUN -eq 1 ]]; then
  rsync -avh --delete --dry-run "${EXCLUDES[@]}" "$SRC/" "$DEST" | tail -30
  exit 0
fi

rsync -avh --delete "${EXCLUDES[@]}" "$SRC/" "$DEST"
echo "▶ Synced."

if [[ $DO_BUILD -eq 1 ]]; then
  echo "▶ Launching Windows build (PowerShell)..."
  # Convert the WSL path to a Windows path and run the PS1 from cmd.exe so
  # PowerShell resolves prereqs from the user's PATH, not WSL's.
  WIN_PATH=$(wslpath -w "${DEST}scripts/build_windows.ps1")
  cmd.exe /c "powershell.exe -ExecutionPolicy Bypass -NoProfile -File ${WIN_PATH}"
fi
