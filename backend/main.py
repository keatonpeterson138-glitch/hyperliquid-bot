"""FastAPI application factory.

Phase 0-B scaffold — just the app shell + health router. Feature routers
(`/candles`, `/slots`, `/orders`, `/markups`, `/layouts`, `/backtest`,
`/research`, `/models`, `/analog`, `/outcomes`, `/audit`, `/killswitch`,
`/stream`) get wired in their respective phases.
"""
from __future__ import annotations

from fastapi import FastAPI

from backend.api import (
    audit,
    candles,
    health,
    killswitch,
    markups,
    outcomes,
    slots,
    stream,
    universe,
    vault,
)


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    Factory pattern so tests can construct a fresh app instance without
    worrying about module-level singletons.
    """
    app = FastAPI(
        title="Hyperliquid Bot Backend",
        version="0.2.0",
        description="Headless trading service for the Hyperliquid desktop app.",
    )
    app.include_router(health.router)
    app.include_router(candles.router)
    app.include_router(outcomes.router)
    app.include_router(universe.router)
    app.include_router(vault.router)
    app.include_router(audit.router)
    app.include_router(killswitch.router)
    app.include_router(slots.router)
    app.include_router(markups.router)
    app.include_router(stream.router)
    return app


# Uvicorn entry point: `uvicorn backend.main:app`
app = create_app()
