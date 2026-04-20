# Building the Installer

Three paths:
1. **WSL → `/mnt/c/Projects/` sync + local build** (matches the existing
   StructDraft workflow — fastest iteration).
2. **GitHub Actions** (zero local setup, build runs on a hosted Windows VM).
3. **Plain local Windows** (if you're not using WSL).

---

## Path A — WSL sync + local Windows build (recommended)

This mirrors how you already build StructDraft: keep the working tree in
WSL, rsync it to `/mnt/c/Projects/hyperliquid-bot/`, then run the
Windows-native build from there.

### One-time — install Windows prereqs

1. [Python 3.12](https://www.python.org/downloads/windows/) — check *Add to PATH*.
2. [Node.js 20 LTS](https://nodejs.org/en/download).
3. [Rust via rustup](https://rustup.rs/). Let it install VS 2022 Build Tools if prompted.

### Every build

From WSL, in the repo root:

```bash
# Sync-only — picks up new commits / local changes.
./scripts/sync_to_windows.sh

# Or sync + build in one command.
./scripts/sync_to_windows.sh --build
```

The `--build` flag invokes `powershell.exe` on the Windows side against
`C:\Projects\hyperliquid-bot\scripts\build_windows.ps1`, which runs
PyInstaller → copies the frozen sidecar into `ui/src-tauri/binaries/` →
`npm install` → `npm run tauri:build`.

Output:

```
C:\Projects\hyperliquid-bot\ui\src-tauri\target\release\bundle\msi\*.msi
C:\Projects\hyperliquid-bot\ui\src-tauri\target\release\bundle\nsis\*.exe
```

Double-click either to install. First build takes ~15 min; subsequent
builds with warm caches take ~2-3 min.

### Preview the sync

```bash
./scripts/sync_to_windows.sh --dry-run
```

Excludes `.venv/`, `node_modules/`, `ui/src-tauri/target/`, `data/`,
`__pycache__/`, PyInstaller output, and existing bundled sidecar binaries.

---

## Path B — GitHub Actions

A Windows-runner workflow is already in the repo at `.github/workflows/build-windows.yml`. It handles PyInstaller bundling + the Tauri build + uploads the `.msi` and `.exe` installers as artifacts.

### Trigger a build

1. Push a tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   This triggers the workflow and attaches the installers to the GitHub Release page.

2. Or trigger manually from the GitHub UI:
   - Go to **Actions** → **build-windows** → **Run workflow** → pick the branch → **Run**.

### Download the installer

- **Tag build:** open https://github.com/keatonpeterson138-glitch/hyperliquid-bot/releases, pick your tag, download the `.msi` or `-setup.exe`.
- **Manual dispatch:** open the workflow run → scroll to **Artifacts** → download `hyperliquid-bot-windows.zip` → unzip for the installers.

### Code signing (optional)

The workflow reads `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` from repo secrets. If set, the installer ships signed; if not, Windows SmartScreen will warn on first run (acceptable for testing). Generate a key with `npx @tauri-apps/cli signer generate -w` and store the output in **Settings → Secrets and variables → Actions**.

---

## Path C — Plain local Windows build (no WSL)

Prerequisites (one-time):
1. [Python 3.12](https://www.python.org/downloads/windows/) — check "Add python.exe to PATH" during install.
2. [Node.js 20 LTS](https://nodejs.org/en/download).
3. [Rust via rustup](https://rustup.rs/). When prompted, let it install VS 2022 Build Tools if they're missing.

Build:
```powershell
cd C:\path\to\hyperliquid-bot
.\scripts\build_windows.ps1
```

Output:
```
ui\src-tauri\target\release\bundle\msi\Hyperliquid Bot_0.2.0_x64_en-US.msi
ui\src-tauri\target\release\bundle\nsis\Hyperliquid Bot_0.2.0_x64-setup.exe
```

First run takes ~15 min (cargo builds 460+ Rust crates). Subsequent runs with the cargo cache warm take ~2-3 min.

Double-click either file to install. The app lands in **Start → Hyperliquid Bot**.

---

## What the installer does

1. Unpacks the Tauri shell (~20 MB) into `%LOCALAPPDATA%\Programs\Hyperliquid Bot\`.
2. Unpacks the PyInstaller backend sidecar (~80-150 MB) next to the Tauri executable.
3. Registers a Start Menu shortcut + desktop shortcut (opt-in in NSIS).
4. On launch, the Tauri shell spawns the sidecar on `127.0.0.1:8787` and shuts it down when you close the window.

No separate Python install is needed on the target machine.

---

## Troubleshooting

- **"backend sidecar not found" on launch.** The PyInstaller output didn't get copied into `ui/src-tauri/binaries/` with the correct target-triple suffix. Re-run `build_windows.ps1` — it handles the copy.
- **SmartScreen "Unrecognized app" warning.** Expected until you sign the installer. Click *More info → Run anyway* for dev use.
- **Port 8787 already in use.** Another Hyperliquid Bot instance, or a dev `uvicorn` you launched. Close it — the sidecar only owns port 8787.
- **PyInstaller build fails with `ModuleNotFoundError`.** Add the missing module to `hiddenimports` in `backend-sidecar.spec`. Common culprits: optional backends of `keyring`, submodules of `hyperliquid`, or a new core dep.

---

## macOS and Linux

Same story, different runners:
- **macOS:** needs a `build-macos.yml` + code-signing cert from Apple Developer. Produces `.dmg`.
- **Linux:** needs a `build-linux.yml`. Produces `.deb` + `.AppImage`. Simpler than the other two — no signing required for AppImage.

These aren't wired yet — Windows is the priority for the current operator. See `internal_docs/PHASE_5p5_TO_12_PLAN.md §3` Phase 12 subtask 3 for the full matrix.
