# Publishing a Release

How to upload a built MSI to GitHub Releases so users can download it.

The MSI is too big to ship inside the git tree (143 MB), so each tagged
version goes up as a GitHub Release with the installer attached. End
users grab it from the Releases page; they never need git or any build
tools.

---

## Prerequisites

- The MSI is already built locally (run `.\scripts\build_windows.ps1` or
  `./scripts/sync_to_windows.sh --build`).
- You have `gh` CLI installed and authenticated:
  ```bash
  gh auth login
  ```

---

## One-shot publish

```bash
# from the repo root
VERSION="v0.2.0"
MSI="ui/src-tauri/target/release/bundle/msi/Hyperliquid Bot_0.2.0_x64_en-US.msi"
NSIS="ui/src-tauri/target/release/bundle/nsis/Hyperliquid Bot_0.2.0_x64-setup.exe"

# tag the commit + push
git tag -a "$VERSION" -m "Release $VERSION"
git push origin "$VERSION"

# create the GitHub release with both installers attached
gh release create "$VERSION" \
    "$MSI" \
    "$NSIS" \
    --title "$VERSION" \
    --notes-file <(cat <<'EOF'
## What's new in v0.2.0

(Pull from internal_docs/Changelog.txt — the latest entry.)

## Install

Download `Hyperliquid Bot_0.2.0_x64_en-US.msi` and double-click.
Windows SmartScreen will warn "publisher unknown" — click **More info → Run anyway**
(the binary isn't code-signed). After install, look for "Hyperliquid Bot" in the Start menu.

See the [install guide](https://github.com/<user>/<repo>/blob/main/docs/install.md)
or the in-app **Tutorial** tab for the full walkthrough.

## SHA-256 checksums

(Optional but recommended — generate via `sha256sum *.msi *.exe`.)

EOF
    )
```

The release shows up at `https://github.com/<owner>/<repo>/releases/tag/v0.2.0`.

---

## What goes in the release notes

Pull the most recent entry from [`internal_docs/Changelog.txt`](../internal_docs/Changelog.txt)
and trim it for end-user consumption. Keep it short — bullet points of:
- New features (user-visible)
- Bug fixes (user-visible)
- Breaking changes (anything that requires re-config or wipe-and-reinstall)

Leave the deep-tech changelog entries (refactors, internal wiring) in the
internal changelog.

---

## After publishing

1. Verify the download works:
   ```bash
   gh release download v0.2.0
   ls -la *.msi *.exe
   ```
2. Bump the in-app version string if you didn't already:
   - `pyproject.toml`
   - `ui/package.json`
   - `ui/src-tauri/Cargo.toml`
   - `ui/src-tauri/tauri.conf.json`
   - `backend/api/health.py`
3. Update `README.md` if any user-facing language needs to change.

---

## Pre-release / RC tags

For early test builds, append `-rc1`, `-rc2`, etc., and add `--prerelease`:

```bash
gh release create "v0.3.0-rc1" "$MSI" --prerelease --title "v0.3.0-rc1"
```

These don't show up as the "latest" release on the project page but are
fully downloadable.

---

## CI-built releases (later)

Eventually wire `.github/workflows/release.yml` to trigger on tag push,
build the MSI on a Windows runner, and attach to the release
automatically. Until then, releases are manual from a developer machine
that has the Windows build chain set up.
