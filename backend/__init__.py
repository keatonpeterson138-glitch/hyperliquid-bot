"""Hyperliquid Bot — FastAPI backend service.

Spawned as a Tauri sidecar by the desktop shell. Exposes REST + WebSocket
endpoints over localhost, consumed by the `ui/` React frontend.

See `internal_docs/OVERHAUL_PLAN.md` §3 (Target Architecture) for the
full service map.
"""
