"""LiveMarketService — thin cache around Hyperliquid's info endpoint.

Hyperliquid exposes ``POST /info`` with body ``{"type": "allMids"}`` etc.
(unauthenticated). This service:
  * Polls allMids in the background (3s cadence) and caches the latest
    mid per symbol so the UI can paint a ticker row without hammering
    the exchange.
  * Fetches meta (universe + per-coin szDecimals, maxLeverage) on demand
    with a 60s cache.
  * Fetches funding history per symbol on demand with a 30s cache.

Falls back gracefully when the network is unavailable — cached value is
returned until it expires; the UI just sees stale numbers, not errors.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAINNET_INFO = "https://api.hyperliquid.xyz/info"
TESTNET_INFO = "https://api.hyperliquid-testnet.xyz/info"

_MIDS_TTL = 3.0     # seconds — how often the poller refreshes allMids
_META_TTL = 60.0
_FUNDING_TTL = 30.0


@dataclass
class TickerSnapshot:
    symbol: str
    price: float | None
    as_of: float = field(default_factory=time.time)


class LiveMarketService:
    def __init__(self, *, testnet: bool = True, timeout: float = 5.0) -> None:
        self.endpoint = TESTNET_INFO if testnet else MAINNET_INFO
        self._client = httpx.Client(timeout=timeout)
        self._lock = threading.RLock()
        self._mids: dict[str, float] = {}
        self._mids_at: float = 0.0
        self._meta: dict[str, Any] | None = None
        self._meta_at: float = 0.0
        self._funding: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()

    # ── lifecycle ─────────────────────────────────────────────────────

    def start_background_poll(self) -> None:
        if self._poller is not None:
            return
        self._poller = threading.Thread(
            target=self._poll_loop, name="live-market-poll", daemon=True,
        )
        self._poller.start()

    def stop(self) -> None:
        self._stop.set()
        if self._poller is not None:
            self._poller.join(timeout=2.0)
            self._poller = None
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    def set_testnet(self, testnet: bool) -> None:
        with self._lock:
            self.endpoint = TESTNET_INFO if testnet else MAINNET_INFO
            self._mids_at = 0.0  # force next read

    # ── public reads ──────────────────────────────────────────────────

    def ticker(self, symbol: str) -> TickerSnapshot:
        mids = self._mids_snapshot()
        return TickerSnapshot(symbol=symbol, price=mids.get(symbol))

    def tickers(self, symbols: list[str]) -> list[TickerSnapshot]:
        mids = self._mids_snapshot()
        return [TickerSnapshot(symbol=s, price=mids.get(s)) for s in symbols]

    def all_mids(self) -> dict[str, float]:
        return dict(self._mids_snapshot())

    def meta(self) -> dict[str, Any]:
        with self._lock:
            if self._meta is not None and (time.time() - self._meta_at) < _META_TTL:
                return self._meta
        data = self._post({"type": "meta"})
        with self._lock:
            self._meta = data
            self._meta_at = time.time()
        return data

    def funding_history(self, symbol: str, lookback_hours: int = 24) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            cached = self._funding.get(symbol)
            if cached is not None and (now - cached[0]) < _FUNDING_TTL:
                return cached[1]
        start_ms = int((now - lookback_hours * 3600) * 1000)
        data = self._post({
            "type": "fundingHistory",
            "coin": symbol,
            "startTime": start_ms,
        })
        rows = data if isinstance(data, list) else []
        with self._lock:
            self._funding[symbol] = (now, rows)
        return rows

    def l2_book(self, symbol: str) -> dict[str, Any]:
        """Current L2 order-book snapshot. Hyperliquid's ``l2Book`` info
        endpoint returns ``{levels: [[bids], [asks]]}`` — we normalise
        to ``{bids: [[px, sz]], asks: [...]}`` (bids high-first, asks low-first)."""
        data = self._post({"type": "l2Book", "coin": symbol})
        levels = data.get("levels") if isinstance(data, dict) else None
        bids: list[list[float]] = []
        asks: list[list[float]] = []
        if isinstance(levels, list) and len(levels) >= 2:
            for lvl in levels[0] or []:
                try:
                    bids.append([float(lvl["px"]), float(lvl["sz"])])
                except (KeyError, TypeError, ValueError):
                    continue
            for lvl in levels[1] or []:
                try:
                    asks.append([float(lvl["px"]), float(lvl["sz"])])
                except (KeyError, TypeError, ValueError):
                    continue
        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "timestamp": data.get("time") if isinstance(data, dict) else None,
        }

    def recent_trades(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        """Recent prints. Hyperliquid ``recentTrades`` returns
        ``[{coin, side, px, sz, hash, time, tid}, ...]``."""
        data = self._post({"type": "recentTrades", "coin": symbol})
        trades = data if isinstance(data, list) else []
        out: list[dict[str, Any]] = []
        for t in trades[:limit]:
            try:
                out.append({
                    "coin": str(t.get("coin", symbol)),
                    "side": str(t.get("side", "")),
                    "price": float(t.get("px", 0)),
                    "size": float(t.get("sz", 0)),
                    "time_ms": int(t.get("time", 0)),
                    "hash": str(t.get("hash", "")),
                })
            except (TypeError, ValueError):
                continue
        return out

    # ── internals ─────────────────────────────────────────────────────

    def _mids_snapshot(self) -> dict[str, float]:
        now = time.time()
        with self._lock:
            stale = (now - self._mids_at) > _MIDS_TTL
            if not stale and self._mids:
                return self._mids
        # Refresh inline if the poller isn't running or is behind.
        try:
            data = self._post({"type": "allMids"})
        except Exception as exc:  # noqa: BLE001
            logger.debug("allMids inline refresh failed: %s", exc)
            with self._lock:
                return self._mids
        mids = _normalize_mids(data)
        with self._lock:
            self._mids = mids
            self._mids_at = now
        return mids

    def _poll_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                data = self._post({"type": "allMids"})
                mids = _normalize_mids(data)
                with self._lock:
                    self._mids = mids
                    self._mids_at = time.time()
                backoff = 1.0
            except Exception as exc:  # noqa: BLE001
                logger.debug("allMids poll failed: %s", exc)
                backoff = min(backoff * 2, 30.0)
            self._stop.wait(max(_MIDS_TTL, backoff))

    def _post(self, payload: dict[str, Any]) -> Any:
        resp = self._client.post(self.endpoint, json=payload)
        resp.raise_for_status()
        return resp.json()


def _normalize_mids(data: Any) -> dict[str, float]:
    """Hyperliquid returns allMids as ``{symbol: "price_str", ...}``."""
    out: dict[str, float] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    return out
