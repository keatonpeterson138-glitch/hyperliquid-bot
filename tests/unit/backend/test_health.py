"""Smoke test for the FastAPI app factory + /health endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


def test_app_factory_returns_configured_app() -> None:
    app = create_app()
    # The health router must be mounted for the Tauri shell to detect liveness.
    routes = [r.path for r in app.routes]
    assert "/health" in routes


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "hyperliquid-bot-backend"
    assert payload["version"] == "0.2.0"
