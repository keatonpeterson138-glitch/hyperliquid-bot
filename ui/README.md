# Hyperliquid Bot — Desktop UI

Tauri 2 + React 19 + TypeScript + Vite.

## Prerequisites

- Node.js ≥ 20 (recommend 24).
- Rust (for Tauri). Install via https://rustup.rs/.
- Platform toolchain:
  - Windows: Visual Studio Build Tools + WebView2.
  - macOS: Xcode CLI.
  - Linux: `webkit2gtk-4.1`, `libayatana-appindicator3-dev`, `librsvg2-dev`, `patchelf`.

## First-time setup

```bash
cd ui
npm install
```

## Dev

```bash
# Vite alone (hits the Python backend if it's running on :8787):
npm run dev

# Tauri shell + Vite + Python sidecar:
npm run tauri:dev
```

## Build

```bash
npm run tauri:build
```

Produces platform installers in `src-tauri/target/release/bundle/`.

## Layout

```
ui/
├── src/                 React app
│   ├── main.tsx         Entry point
│   ├── App.tsx          Shell
│   └── App.css
├── src-tauri/           Rust Tauri shell
│   ├── Cargo.toml
│   ├── tauri.conf.json  Tauri config (sidecar, updater, plugins)
│   └── src/
│       └── main.rs      Rust entry; spawns backend sidecar (Phase 2+)
├── package.json
├── vite.config.ts
├── tsconfig.json
└── index.html
```

## Status

This is Phase 0-B scaffold. No workspace views wired yet — only a
health-check probe against the FastAPI backend. Phase 3 builds the real
shell, Phase 4 adds the chart workspace, etc. — see
[`../todo/path_to_v1.md`](../todo/path_to_v1.md).
