"""FastAPI application factory.

Production DI is wired in :func:`create_app` via ``app.dependency_overrides``
so tests can freely swap any service for a fake. Services that need live
exchange / network access (``KillSwitchService``, ``TradeEngineService``,
``PriceBinaryModel``) intentionally stay on their 503 stubs here — they
get wired at slot-runner startup with real credentials out of the
``KeyVault``. The UI treats 503 as "not configured yet" and renders a
hint rather than crashing.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import analog as analog_api
from backend.api import audit as audit_api
from backend.api import (
    backtest as backtest_api,
)
from backend.api import (
    candles,
    health,
)
from backend.api import credentials as credentials_api
from backend.api import killswitch as killswitch_api
from backend.api import logs as logs_api
from backend.api import markets as markets_api
from backend.api import markups as markups_api
from backend.api import models as models_api
from backend.api import news as news_api
from backend.api import notes as notes_api
from backend.api import orders as orders_api
from backend.api import outcomes as outcomes_api
from backend.api import research as research_api
from backend.api import settings as settings_api
from backend.api import slots as slots_api
from backend.api import stream as stream_api
from backend.api import universe as universe_api
from backend.api import vault as vault_api
from backend.api import wallet as wallet_api
from backend.db.app_db import AppDB
from backend.db.duckdb_catalog import DuckDBCatalog
from backend.db.paths import DEFAULT_DATA_ROOT
from backend.services.audit import AuditService
from backend.services.backtest import BacktestEngine
from backend.services.key_vault import KeyVault
from backend.services.kill_switch import KillSwitchService
from backend.services.markup_store import MarkupStore
from backend.services.order_repository import OrderRepository
from backend.services.order_service import OrderService
from backend.services.slot_repository import SlotRepository
from backend.services.stream_hub import StreamHub
from backend.services.universe_manager import UniverseManager


class _NoopExchange:
    """Dev stub for ``EmergencyExchange``. Real client gets swapped in when
    the vault is unlocked (Phase 11 hardening)."""

    def cancel_all(self) -> list[dict]:  # type: ignore[type-arg]
        return []

    def get_all_positions(self) -> list[dict]:  # type: ignore[type-arg]
        return []

    def close_position(self, symbol: str, dex: str = "") -> dict:  # type: ignore[type-arg]
        return {"symbol": symbol, "dex": dex, "skipped": True}

logger = logging.getLogger(__name__)

_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5177",
    "http://localhost:5177",
    "tauri://localhost",
    "http://tauri.localhost",
)


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return list(_DEFAULT_CORS_ORIGINS)


def _db_path() -> Path:
    raw = os.environ.get("BACKEND_DB_PATH")
    return Path(raw) if raw else Path("data") / "app.db"


def _wire_services(app: FastAPI) -> None:
    """Construct in-process singletons and override the router DI stubs.

    Only services with no network dependencies are wired here. Exchange-
    facing services (KillSwitch, TradeEngine, PriceBinaryModel) remain on
    their 503 stubs — they come alive when the user unlocks the vault.
    """
    db = AppDB(_db_path())
    hub = StreamHub()
    markup_store = MarkupStore(db)
    universe = UniverseManager(db)
    audit = AuditService(db)
    slot_repo = SlotRepository(db)
    key_vault = KeyVault()
    kill_switch = KillSwitchService(_NoopExchange(), db, audit)
    # Backtest wiring — uses the DuckDB catalog over the Parquet lake.
    bt_catalog = DuckDBCatalog(DEFAULT_DATA_ROOT)

    def _candle_query(symbol, interval, from_ts, to_ts):
        with bt_catalog:
            return bt_catalog.query_candles(symbol, interval, from_ts, to_ts)

    backtest_engine = BacktestEngine(candle_query=_candle_query)
    backtest_registry = backtest_api.BacktestRegistry()

    # Backfill service — powers /backfill, /candles auto-fetch, /candles/refresh.
    # Lazy import so packaging tests don't pull network deps at import time.
    try:
        backfill_service = candles.build_default_backfill_service()
        candles.install_backfill_service(backfill_service)
    except Exception as exc:  # noqa: BLE001
        logger.warning("backfill service unavailable: %s", exc)
        backfill_service = None

    from backend.services.analog import AnalogEngine
    analog_engine = AnalogEngine(candle_query=_candle_query)

    from backend.services.ml import ModelRegistry
    model_registry = ModelRegistry(db)

    from backend.services.settings_store import SettingsStore
    settings_store = SettingsStore()

    from backend.services.notes_store import NotesStore
    notes_store = NotesStore(db)

    # Live market data — polls Hyperliquid's info endpoint every ~3s
    # in a background thread. Testnet toggle lives in Settings.
    from backend.services.live_market import LiveMarketService
    live_market = LiveMarketService(testnet=settings_store.all().testnet)
    live_market.start_background_poll()
    app.state.live_market = live_market

    # Credentials store — third-party API keys (Binance, Alpha Vantage,
    # etc.); Hyperliquid private keys remain in KeyVault.
    from backend.services.credentials_store import CredentialsStore
    credentials_store = CredentialsStore(db)

    # News monitor — RSS + CryptoPanic poller. Kept off by default in
    # dev to avoid noisy logs; the Dashboard panel's first GET lazy-
    # starts it on demand.
    from core.news_monitor import NewsMonitor
    news_monitor = NewsMonitor(poll_interval=60)
    try:
        news_monitor.start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("news monitor failed to start: %s", exc)
    app.state.news_monitor = news_monitor

    order_repo = OrderRepository(db)
    # Gateway stays None in dev until the vault is unlocked and a real
    # exchange client is constructed. OrderService accepts None and marks
    # orders as 'pending' local-only — good enough to render the chart-
    # to-order UI without risking a testnet trade during hot-reload.
    order_service = OrderService(order_repo, gateway=None, audit=audit, markup_store=markup_store)

    from backend.services.wallet import WalletService
    wallet_service = WalletService(order_repo, audit)

    app.state.db = db
    app.state.stream_hub = hub
    app.state.markup_store = markup_store
    app.state.universe_manager = universe
    app.state.audit_service = audit
    app.state.slot_repository = slot_repo
    app.state.key_vault = key_vault
    app.state.kill_switch = kill_switch
    app.state.order_repository = order_repo
    app.state.order_service = order_service

    app.dependency_overrides[stream_api.get_stream_hub] = lambda: hub
    app.dependency_overrides[markups_api.get_markup_store] = lambda: markup_store
    app.dependency_overrides[universe_api.get_universe_manager] = lambda: universe
    app.dependency_overrides[audit_api.get_audit_service] = lambda: audit
    app.dependency_overrides[slots_api.get_slot_repo] = lambda: slot_repo
    app.dependency_overrides[vault_api.get_vault] = lambda: key_vault
    app.dependency_overrides[killswitch_api.get_kill_switch] = lambda: kill_switch
    app.dependency_overrides[orders_api.get_order_service] = lambda: order_service
    app.dependency_overrides[orders_api.get_markup_store_for_orders] = lambda: markup_store
    app.dependency_overrides[backtest_api.get_backtest_engine] = lambda: backtest_engine
    app.dependency_overrides[backtest_api.get_backtest_registry] = lambda: backtest_registry
    if backfill_service is not None:
        app.dependency_overrides[candles.get_backfill_service] = lambda: backfill_service
    app.dependency_overrides[markets_api.get_live_market] = lambda: live_market
    app.dependency_overrides[credentials_api.get_credentials_store] = lambda: credentials_store
    app.dependency_overrides[news_api.get_news_monitor] = lambda: news_monitor
    app.dependency_overrides[analog_api.get_analog_engine] = lambda: analog_engine
    app.dependency_overrides[models_api.get_model_registry] = lambda: model_registry
    app.dependency_overrides[settings_api.get_settings_store] = lambda: settings_store
    app.dependency_overrides[notes_api.get_notes_store] = lambda: notes_store
    app.dependency_overrides[wallet_api.get_wallet_service] = lambda: wallet_service


@asynccontextmanager
async def _lifespan(app: FastAPI):
    logs_api.configure_file_logging()
    _wire_services(app)
    try:
        yield
    finally:
        db: AppDB | None = getattr(app.state, "db", None)
        if db is not None:
            db.close()


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    Factory pattern so tests can construct a fresh app instance without
    worrying about module-level singletons.
    """
    app = FastAPI(
        title="Hyperliquid Bot Backend",
        version="0.2.0",
        description="Headless trading service for the Hyperliquid desktop app.",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def _root() -> dict[str, str]:
        return {
            "service": "hyperliquid-bot-backend",
            "health": "/health",
            "docs": "/docs",
        }

    app.include_router(health.router)
    app.include_router(candles.router)
    app.include_router(outcomes_api.router)
    app.include_router(universe_api.router)
    app.include_router(vault_api.router)
    app.include_router(audit_api.router)
    app.include_router(killswitch_api.router)
    app.include_router(slots_api.router)
    app.include_router(markups_api.router)
    app.include_router(orders_api.router)
    app.include_router(backtest_api.router)
    app.include_router(research_api.router)
    app.include_router(analog_api.router)
    app.include_router(models_api.router)
    app.include_router(settings_api.router)
    app.include_router(notes_api.router)
    app.include_router(wallet_api.router)
    app.include_router(logs_api.router)
    app.include_router(markets_api.router)
    app.include_router(credentials_api.router)
    app.include_router(news_api.router)
    app.include_router(stream_api.router)
    return app


# Uvicorn entry point: `uvicorn backend.main:app`
app = create_app()
