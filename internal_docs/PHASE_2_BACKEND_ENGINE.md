# Phase 2 — Backend + Trade Engine + Safety Scaffolding: Implementation Plan

**Goal:** Every capability the current `dashboard.py` has, reachable over HTTP/WS; mainnet hardening scaffolded from day one; no UI change yet.

**Scope:** 2 weeks at 1 FTE. ~8 commits.

**Prerequisites:** Phase 1 complete (data platform queryable). `engine.py` already extracted (Phase 0-A). `backend/` scaffold already exists (Phase 0-B).

**Companion docs:** `OVERHAUL_PLAN.md §13` (mainnet hardening spec), `Design.md §6` (target architecture), `engine.py` (pure decision layer).

---

## 1. Target End State

After Phase 2, the following must work without any Tauri UI:

- `curl -X POST localhost:8787/slots -d '{...}'` creates a slot; `GET /slots` lists it.
- `POST /slots/{id}/start` begins the trading loop for that slot, running the TradeEngine each interval.
- Slot events stream on `WS /stream` — `tick`, `candle_close`, `signal`, `order_filled`, `position_update`, `pnl_update`, `log`, `kill_switch_activated`, `shadow_divergence`.
- `POST /killswitch/activate` flattens all positions and cancels all orders within 2 s, writes to audit.
- `POST /vault/unlock` unlocks OS keychain; private key never touches disk.
- `GET /audit` returns every order / modify / cancel / fill / kill-switch event with full context, CSV-exportable.
- `GET /universe` lists every Hyperliquid market discovered at startup (native + HIP-3 + HIP-4).
- `POST /universe/tag` lets the user tag subsets (trade / train / watch).

`bot.py` and `dashboard.py` still work unchanged, running their own loops — they're still the primary UX surface until Phase 3.

---

## 2. Architecture (Phase 2 scope within target)

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI app (backend/main.py)                                  │
│                                                                 │
│  Routers (backend/api/)                                         │
│    /health (Phase 0-B)   ─── ✓                                  │
│    /universe             ─── NEW P2.1                           │
│    /vault                ─── NEW P2.3                           │
│    /audit                ─── NEW P2.4                           │
│    /killswitch           ─── NEW P2.5                           │
│    /slots                ─── NEW P2.7                           │
│    /orders /positions /balance ── NEW P2.7                      │
│    /stream (WS)          ─── NEW P2.7                           │
│                                                                 │
│  Domain services (backend/services/)                            │
│    UniverseManager       ─── P2.1                               │
│    KeyVault              ─── P2.3                               │
│    AuditService          ─── P2.4                               │
│    KillSwitchService     ─── P2.5                               │
│    TradeEngineService    ─── P2.6   (wraps engine.py)           │
│    SlotRunner            ─── P2.6   (one-per-slot executor)     │
│    ShadowClient          ─── P2.8                               │
│                                                                 │
│  Persistence (backend/db/)                                      │
│    app_db                ─── P2.2   (sqlite: markets, tags,     │
│                                       audit, slots)             │
│    Parquet + DuckDB      ─── ✓ (Phase 1)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Commit Plan (ordered)

### P2.1 — UniverseManager + `/universe` API

**Files:**
- `backend/services/universe_manager.py`
- `backend/models/market.py` — Pydantic `Market` + `MarketTag`
- `backend/api/universe.py` — routers
- `tests/unit/backend/services/test_universe_manager.py`
- `tests/unit/backend/api/test_universe.py`

**Interface:**
```python
class UniverseManager:
    def __init__(self, info: Info, outcome_client: OutcomeClient, db: AppDB): ...
    def refresh(self) -> list[Market]: ...       # full re-scan
    def active_markets(self) -> list[Market]: ...
    def get(self, market_id: str) -> Market | None: ...
    def tag(self, market_id: str, tag: str) -> None: ...
    def untag(self, market_id: str, tag: str) -> None: ...
    def markets_by_tag(self, tag: str) -> list[Market]: ...
```

**Discovery flow:**
```
UniverseManager.refresh():
  1. info.meta()                     → native perps
  2. for dex in self._known_dexes:   → HIP-3 per dex
        info.meta(dex=dex)
  3. outcome_client.list_markets()   → HIP-4
  4. normalize each into Market
  5. db.upsert_markets(markets)      → SQLite markets table
  6. db.set_inactive_if_missing(...) → soft-delete stale
  7. return markets
```

**HIP-3 dex discovery:** Start with hardcoded list `["cash", "xyz"]`. Expose `add_known_dex()` + `/universe/dexes` for user-added builder dexes as HIP-3 grows. Later: scrape from an on-chain registry if Hyperliquid exposes one.

**Endpoints:**
```
GET    /universe                      → list[Market]
GET    /universe/{market_id}          → Market
POST   /universe/refresh              → { markets_added, markets_removed }
POST   /universe/{market_id}/tag      body: { tag: "train" }
DELETE /universe/{market_id}/tag      body: { tag: "train" }
GET    /universe/tag/{tag}            → list[Market]
```

**Test coverage:**
- Mocked `Info.meta` + `Info.meta(dex=...)` + `OutcomeClient.list_markets` → refresh produces expected Market rows.
- Soft-delete: market absent on refresh → `active=False`, kept in DB (for audit history).
- Tagging CRUD via TestClient.

**Risk:** Hyperliquid SDK version compatibility — wrap the `meta()` call in a small `_fetch_meta_safely()` that catches unknown-field errors and logs, so a breaking SDK update doesn't brick startup.

---

### P2.2 — `app_db` (SQLite) + initial schema

**Files:**
- `backend/db/app_db.py` — `AppDB` class, connection, init, thread-safe access.
- `backend/db/migrations/__init__.py`
- `backend/db/migrations/001_initial.sql` — markets, market_tags, audit_log, slots.
- `backend/db/migrations/migrate.py` — minimal migrator (version table, apply-in-order).
- `tests/unit/backend/db/test_app_db.py`

**Schema (migration 001):**
```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE markets (
  id              TEXT PRIMARY KEY,     -- 'perp:BTC' | 'perp:xyz:TSLA' | 'outcome:0x...'
  kind            TEXT NOT NULL CHECK (kind IN ('perp','outcome')),
  symbol          TEXT NOT NULL,
  dex             TEXT NOT NULL DEFAULT '',
  base            TEXT,
  category        TEXT,
  subcategory     TEXT,
  max_leverage    INTEGER,
  sz_decimals     INTEGER,
  tick_size       REAL,
  min_size        REAL,
  resolution_date TIMESTAMP,            -- outcomes only
  bounds_json     TEXT,                 -- outcomes only
  active          INTEGER NOT NULL DEFAULT 1,
  first_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_markets_kind_active ON markets(kind, active);
CREATE INDEX idx_markets_category    ON markets(category);

CREATE TABLE market_tags (
  market_id TEXT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  tag       TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (market_id, tag)
);
CREATE INDEX idx_market_tags_tag ON market_tags(tag);

CREATE TABLE audit_log (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  event_type            TEXT NOT NULL,
  slot_id               TEXT,
  strategy              TEXT,
  symbol                TEXT,
  side                  TEXT,
  size_usd              REAL,
  price                 REAL,
  reason                TEXT,
  exchange_response_json TEXT,
  source                TEXT NOT NULL
);
CREATE INDEX idx_audit_ts      ON audit_log(ts);
CREATE INDEX idx_audit_symbol  ON audit_log(symbol);
CREATE INDEX idx_audit_slot    ON audit_log(slot_id);
-- Append-only enforcement
CREATE TRIGGER audit_log_no_update
  BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_log_no_delete
  BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TABLE slots (
  id                     TEXT PRIMARY KEY,          -- uuid4
  kind                   TEXT NOT NULL CHECK (kind IN ('perp','outcome')),
  symbol                 TEXT NOT NULL,
  interval               TEXT,                      -- null for outcome slots
  strategy               TEXT NOT NULL,
  strategy_params_json   TEXT NOT NULL DEFAULT '{}',
  size_usd               REAL NOT NULL,
  leverage               INTEGER,                   -- null for outcome
  stop_loss_pct          REAL,
  take_profit_pct        REAL,
  enabled                INTEGER NOT NULL DEFAULT 0,
  shadow_enabled         INTEGER NOT NULL DEFAULT 0,
  -- Advanced flags (from current dashboard.py SLOT_* config)
  trailing_sl            INTEGER DEFAULT 0,
  mtf_enabled            INTEGER DEFAULT 1,
  regime_filter          INTEGER DEFAULT 0,
  atr_stops              INTEGER DEFAULT 0,
  loss_cooldown          INTEGER DEFAULT 0,
  volume_confirm         INTEGER DEFAULT 0,
  rsi_guard              INTEGER DEFAULT 0,
  rsi_guard_low          REAL DEFAULT 30.0,
  rsi_guard_high         REAL DEFAULT 70.0,
  ml_model_id            TEXT,                      -- promotes a trained model to live
  created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_slots_enabled ON slots(enabled);

-- Track slot runtime state (restart recovery)
CREATE TABLE slot_state (
  slot_id       TEXT PRIMARY KEY REFERENCES slots(id) ON DELETE CASCADE,
  last_tick_at  TIMESTAMP,
  last_signal   TEXT,
  last_decision_action TEXT,
  current_position TEXT,      -- 'LONG' | 'SHORT' | null
  entry_price   REAL,
  position_size_usd REAL,
  open_order_ids TEXT         -- json array
);

INSERT INTO schema_version(version) VALUES (1);
```

**Test coverage:**
- Fresh init creates all tables + `schema_version` row.
- `migrate()` twice is idempotent.
- Audit triggers block UPDATE and DELETE (expect `OperationalError`).
- Slot insert + read round-trip with all fields.
- Foreign-key cascade: deleting a slot drops its `slot_state` row.

**Risk:** SQLite file corruption on crash — WAL mode + periodic `PRAGMA wal_checkpoint`.

---

### P2.3 — KeyVault + `/vault` API

**Files:**
- `backend/services/key_vault.py`
- `backend/api/vault.py`
- `tests/unit/backend/services/test_key_vault.py`

**Interface:**
```python
class KeyVault:
    def __init__(self, service_name: str = "hyperliquid-bot"): ...
    def store_key(self, wallet_address: str, private_key: str) -> None: ...
    def unlock(self, wallet_address: str) -> None: ...      # pulls into memory
    def get_private_key(self) -> str: ...                   # raises LockedError if not unlocked
    def lock(self) -> None: ...                             # clears memory
    def is_unlocked(self) -> bool: ...
    def wipe(self, wallet_address: str) -> None: ...        # delete from keychain
```

**Backend:** `keyring` Python lib. Backends:
- Windows: Credential Manager.
- macOS: Keychain.
- Linux: libsecret (GNOME Keyring / KWallet via DBus).
- CI / headless: `keyrings.alt` fallback, or in-memory fake for tests.

**Endpoints:**
```
POST /vault/store     body: { wallet_address, private_key }
                      → 204, key wiped from request log
POST /vault/unlock    body: { wallet_address }
                      → 200 { unlocked_at }
POST /vault/lock      → 204
GET  /vault/status    → { unlocked: bool, wallet_address: str | null }
DELETE /vault/{wallet_address}
                      → 204
```

**Security:**
- Private keys never written to disk by the app.
- `.env` fallback only if `DEV_MODE=1` (big log warning).
- Request / response logging for `/vault` routes strips the `private_key` field.
- Never return the private key over the wire — only "unlocked: true".

**Test coverage:**
- Fake keyring backend stores → unlock → `get_private_key()` returns what was stored.
- `lock()` clears memory; next `get_private_key()` raises.
- Wipe removes the secret from keyring.
- `/vault/store` response never contains the private key.

**Risk:** CI has no keychain. Tests use a fake backend via `keyring.set_keyring()`.

---

### P2.4 — AuditService + `/audit` API

**Files:**
- `backend/services/audit.py`
- `backend/models/audit.py` — Pydantic `AuditEvent`.
- `backend/api/audit.py`
- `tests/unit/backend/services/test_audit.py`
- `tests/unit/backend/api/test_audit.py`

**Interface:**
```python
class AuditService:
    def __init__(self, db: AppDB): ...
    def log(
        self,
        event_type: str,
        *,
        slot_id: str | None = None,
        strategy: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        size_usd: float | None = None,
        price: float | None = None,
        reason: str | None = None,
        exchange_response: dict | None = None,
        source: str,
    ) -> None: ...
    
    def query(
        self,
        *,
        event_types: list[str] | None = None,
        symbol: str | None = None,
        slot_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[AuditEvent]: ...
```

**Event types (at minimum):**
- `order_placed`, `order_modified`, `order_cancelled`, `order_filled`
- `position_opened`, `position_closed`
- `slot_started`, `slot_stopped`, `slot_updated`
- `decision_emitted`, `decision_executed`, `decision_rejected`
- `risk_breach`, `shadow_divergence`
- `key_unlock`, `key_wipe`, `key_store`
- `kill_switch_activated`, `kill_switch_step`
- `universe_refreshed`, `config_change`

**Endpoints:**
```
GET /audit?event_type=&symbol=&slot_id=&since=&until=&limit=
    → list[AuditEvent]
GET /audit.csv?...  (same filters)
    → CSV download
```

**Test coverage:**
- Round-trip: log → query returns event.
- Filter by event_type + date range.
- CSV export writes correct headers + row count.
- UPDATE/DELETE attempts on `audit_log` table raise (trigger verification).

---

### P2.5 — KillSwitchService + `/killswitch` API

**Files:**
- `backend/services/kill_switch.py`
- `backend/api/killswitch.py`
- `tests/unit/backend/services/test_kill_switch.py`

**Interface:**
```python
class KillSwitchService:
    def __init__(
        self,
        exchange: HyperliquidClient,
        db: AppDB,
        audit: AuditService,
        stream_hub: StreamHub,
    ): ...
    
    def activate(self, *, source: str = "user", confirmation: str) -> KillSwitchReport: ...
    def is_active(self) -> bool: ...
    def reset(self, *, source: str = "user") -> None: ...
```

**Activation flow (atomic, audited per step):**
```
activate(confirmation):
  if confirmation != "KILL":
      raise ValueError("Fat-finger guard")
  
  audit.log('kill_switch_activated', source=source)
  stream_hub.broadcast('kill_switch_activating')
  
  report = KillSwitchReport()
  
  # Step 1: cancel all open orders
  try:
    cancelled = exchange.cancel_all()
    audit.log('kill_switch_step', reason=f'cancelled {len(cancelled)} orders')
    report.orders_cancelled = cancelled
  except Exception as e:
    audit.log('kill_switch_step', reason=f'cancel_all failed: {e}')
    report.errors.append(...)
  
  # Step 2: close every open position
  positions = exchange.get_all_positions()
  for pos in positions:
    try:
      result = exchange.close_position(pos.symbol, dex=pos.dex)
      audit.log('kill_switch_step', symbol=pos.symbol, reason='closed')
    except Exception as e:
      audit.log('kill_switch_step', symbol=pos.symbol, reason=f'close failed: {e}')
      report.errors.append(...)
  
  # Step 3: disable all slots
  db.set_all_slots_enabled(False)
  audit.log('kill_switch_step', reason='all slots disabled')
  
  # Step 4: set "killed" flag, UI respects it
  self._state = ACTIVE
  stream_hub.broadcast('kill_switch_activated', report)
  
  return report
```

**Endpoints:**
```
POST /killswitch/activate    body: { confirmation: "KILL", source?: str }
                             → { orders_cancelled, positions_closed, errors }
GET  /killswitch/status      → { active: bool, last_activated: ts | null }
POST /killswitch/reset       body: { confirmation: "RESUME" }
                             → 204 (requires all positions flat)
```

**Test coverage:**
- Mock exchange → activate cancels + closes + disables slots in right order.
- Partial failure: one close fails → still proceeds with next, collects in `errors`.
- Audit log has one entry per step.
- Confirmation guard: wrong string raises.
- Double-activation is a no-op (idempotent).

---

### P2.6 — TradeEngineService + SlotRunner

**Files:**
- `backend/services/trade_engine_service.py` — multi-slot orchestrator.
- `backend/services/slot_runner.py` — single-slot executor.
- `backend/services/order_executor.py` — translates `Decision` into exchange calls.
- `backend/models/slot.py`, `backend/models/decision.py`
- `tests/unit/backend/services/test_trade_engine_service.py`
- `tests/unit/backend/services/test_slot_runner.py`
- `tests/unit/backend/services/test_order_executor.py`

**Relationship to `engine.py`:**
`engine.TradeEngine` stays unchanged — still the pure decision function. This phase builds the **service** layer around it: thread pool for N slots, exchange client wiring, event emission, persistent state.

**SlotRunner flow per interval:**
```
SlotRunner.tick(slot):
  # 1. Assemble EngineContext from live state
  ctx = EngineContext(
    symbol=slot.symbol,
    current_price=exchange.get_market_price(slot.symbol),
    candles_df=data_catalog.query_candles(
      slot.symbol, slot.interval,
      start=now - slot.lookback_bars * interval_duration,
      end=now),
    current_position=state.current_position,
    entry_price=state.entry_price,
    open_position_count=exchange.count_open_positions(),
  )
  
  # 2. Pure decision
  engine = TradeEngine(
    strategy=strategy_factory.get(slot.strategy, **slot.strategy_params),
    risk=RiskManagerForSlot(slot),
  )
  decision = engine.decide(ctx)
  
  # 3. Audit + broadcast regardless of action
  audit.log('decision_emitted', slot_id=slot.id, ...)
  stream_hub.emit('signal', slot_id=slot.id, decision=decision)
  
  # 4. Execute if actionable
  if decision.is_actionable:
    order_executor.execute(decision, slot, exchange)
    audit.log('decision_executed', ...)
  else:
    if decision.rejection:
      audit.log('decision_rejected', reason=decision.rejection)
  
  # 5. Persist slot_state
  db.update_slot_state(slot.id, last_tick_at=now, last_decision_action=decision.action, ...)
  stream_hub.emit('pnl_update', slot_id=slot.id, ...)
```

**TradeEngineService orchestration:**
```
class TradeEngineService:
    def __init__(self, db, exchange, data_catalog, audit, stream_hub, kill_switch): ...
    
    def start_slot(slot_id): ...   # spawn SlotRunner in pool
    def stop_slot(slot_id): ...
    def start_all_enabled(): ...   # on app boot
    def stop_all(): ...            # on shutdown
    def get_slot_runner(slot_id) -> SlotRunner | None: ...
```

Thread pool: `concurrent.futures.ThreadPoolExecutor(max_workers=N)`. Each slot gets a `PeriodicScheduler` task that wakes every `loop_interval_sec` and calls `tick()`.

**OrderExecutor contract:**
```python
class OrderExecutor:
    def execute(self, decision: Decision, slot: Slot, exchange: HyperliquidClient) -> ExecutionResult: ...

# Maps Decision → exchange calls
# OPEN_LONG  → exchange.place_market_order(symbol, is_buy=True, size_usd, leverage)
# OPEN_SHORT → exchange.place_market_order(symbol, is_buy=False, size_usd, leverage)
# CLOSE_LONG / CLOSE_SHORT → exchange.close_position(symbol)
# Then: place SL + TP as bracket orders if slot.stop_loss_pct / take_profit_pct set.
```

**Test coverage:**
- Fake exchange + strategy → tick once → assert order placed, audit rows written, stream events emitted.
- Kill-switch trips mid-tick → tick aborts, no order placed.
- Slot disabled → start_slot() refuses.
- Multi-slot: 3 slots running → each gets independent state.

**Risk:** Thread safety for SQLite writes — serialise via a single writer thread or use `PRAGMA busy_timeout`.

---

### P2.7 — REST + WS for slots, orders, positions, balance, stream

**Files:**
- `backend/api/slots.py`
- `backend/api/orders.py`
- `backend/api/positions.py`
- `backend/api/balance.py`
- `backend/api/stream.py`
- `backend/services/stream_hub.py` — WS fan-out.
- `tests/unit/backend/api/test_slots.py`
- `tests/unit/backend/api/test_orders.py`
- `tests/unit/backend/api/test_stream.py`

**Endpoints:**
```
# Slots
GET    /slots                 → list[Slot]
POST   /slots                 body: SlotCreate → Slot
GET    /slots/{id}            → Slot + SlotState
PATCH  /slots/{id}            body: partial Slot → Slot
DELETE /slots/{id}            → 204 (soft delete)
POST   /slots/{id}/start      → 204
POST   /slots/{id}/stop       → 204
POST   /slots/start-all       → 204
POST   /slots/stop-all        → 204

# Orders (manual, not strategy-driven)
GET    /orders                → list[Order] (open)
POST   /orders                body: OrderCreate → Order (placed on exchange)
PATCH  /orders/{order_id}     body: { price?, size? } → Order
DELETE /orders/{order_id}     → 204

# Positions
GET    /positions             → list[Position]
POST   /positions/{symbol}/close → 204

# Balance
GET    /balance               → { equity, margin, buying_power, positions_value }

# Stream (WebSocket)
WS     /stream                → multiplexed events (subscribe by type)
```

**WS event envelope:**
```json
{
  "type": "signal" | "candle_close" | "order_filled" | "position_update" | "pnl_update" |
           "log" | "kill_switch_activated" | "shadow_divergence" | "universe_refreshed",
  "ts": "2026-04-20T15:33:00Z",
  "slot_id": "uuid",
  "payload": { ... }
}
```

Subscribers send `{"subscribe": ["signal", "pnl_update"]}` on connect.

**Test coverage:**
- Full CRUD on slots via TestClient.
- Start → tick → event received on WS client (using `TestClient.websocket_connect`).
- Order place → audit log entry + ws broadcast.

---

### P2.8 — ShadowClient + `/slots/{id}/shadow_enabled` toggle

**Files:**
- `backend/services/shadow_client.py`
- Modifications to `backend/services/slot_runner.py` — fork run when `slot.shadow_enabled`.
- `tests/unit/backend/services/test_shadow_client.py`

**Flow:**
```
SlotRunner.tick(slot):
  decision_main = engine.decide(ctx_main)
  
  if slot.shadow_enabled:
    # Shadow runs against testnet with same strategy + same candles
    shadow_exchange = HyperliquidClient(testnet=True, ...)
    ctx_shadow = dataclasses.replace(ctx_main,
        current_price=shadow_exchange.get_market_price(slot.symbol),
        current_position=shadow_state.current_position,
        entry_price=shadow_state.entry_price)
    decision_shadow = engine.decide(ctx_shadow)
    
    if decision_main.action != decision_shadow.action:
      audit.log('shadow_divergence',
                slot_id=slot.id,
                reason=f'main={decision_main.action}, shadow={decision_shadow.action}')
      stream_hub.emit('shadow_divergence', ...)
    
    # Execute shadow decision too — tracks shadow P&L separately
    shadow_executor.execute(decision_shadow, slot, shadow_exchange)
  
  # Always execute main
  if decision_main.is_actionable:
    order_executor.execute(decision_main, slot, exchange)
```

**Test coverage:**
- Shadow-enabled slot → two executions (main + testnet).
- Divergence → audit + stream event.
- Shadow P&L tracked separately in `shadow_trades` table.

**Deferred to Phase 11:** UI panel showing shadow divergence alerts, P&L comparison chart.

---

## 4. Dependencies Added in Phase 2

```
# requirements.txt additions
keyring>=25.0.0                   # OS keychain
python-jose[cryptography]>=3.3.0  # JWT for local-auth tokens (future)
# (Optional; evaluate)
aiosqlite>=0.20.0                 # async sqlite if we go full-async
```

---

## 5. Data Flows

### 5.1 User starts a slot end-to-end

```
UI ── POST /slots { symbol: "BTC", interval: "1h", strategy: "ema_crossover", ... }
                                                         │
                                                         ▼
                                           backend/api/slots.create()
                                                         │
                                                         ▼
                                              app_db.insert_slot(...)
                                                         │
                                                         ▼
                                       audit.log('slot_created', ...)
                                                         │
                                                         ▼
                                            stream_hub.emit('slot_created')

UI ── POST /slots/{id}/start
                      │
                      ▼
     TradeEngineService.start_slot(id)
                      │
                      ▼
     ThreadPool submits SlotRunner(slot).run_forever()
                      │
     ┌──────────── every loop_interval_sec ────────────┐
     ▼                                                 │
  ctx = build_engine_context(slot)  ──────▶  engine.decide(ctx)
                                                       │
                         ┌──────────── Decision ───────┘
                         ▼
          audit.log('decision_emitted', ...)
                         │
                         ▼
          if decision.is_actionable:
             order_executor.execute(decision, slot)
                         │
                         ▼
                exchange.place/close/modify
                         │
                         ▼
          audit.log('order_placed' | 'position_closed', ...)
                         │
                         ▼
          stream_hub.emit('order_filled', ...) → UI
```

### 5.2 Kill switch cascade

```
UI ── POST /killswitch/activate { confirmation: "KILL" }
                      │
                      ▼
         KillSwitchService.activate()
                      │
         ┌────────────┼────────────┬────────────┐
         ▼            ▼            ▼            ▼
  cancel_all()   close_all pos   disable slots  audit + broadcast
                      │
                      ▼
           exchange.cancel_all()
           exchange.get_all_positions()
           for pos: exchange.close_position(pos.symbol)
           db.set_all_slots_enabled(False)
                      │
                      ▼
              audit.log('kill_switch_activated' + per-step)
                      │
                      ▼
              stream_hub.broadcast('kill_switch_activated')
                      │
                      ▼
                    UI banner + disable trade surfaces
```

### 5.3 Shadow divergence

```
SlotRunner.tick(slot):
   ctx_main   = build from mainnet state
   ctx_shadow = build from testnet state
   
   dec_main   = engine.decide(ctx_main)
   dec_shadow = engine.decide(ctx_shadow)
   
   if dec_main.action != dec_shadow.action:
       audit.log('shadow_divergence', ...)
       stream_hub.emit('shadow_divergence', payload)
   
   order_executor.execute(dec_main,  slot, mainnet_exchange)
   order_executor.execute(dec_shadow, slot, testnet_exchange)   # shadow P&L
```

---

## 6. Testing Strategy

- **Unit:** every service with mocked dependencies. No exchange, no keyring, no network.
- **Integration:** `@pytest.mark.integration` for full `TestClient` → FastAPI → mocked exchange → sqlite roundtrips. Run in CI.
- **No keyring in CI:** use `keyring.set_keyring(InMemoryKeyring())` in a conftest fixture.
- **No threads in tests:** `SlotRunner.tick()` is callable directly. `TradeEngineService.start_slot()` uses a `sync_run_once` hook for testing.
- **Audit verification:** every service test asserts the expected audit row was written.

---

## 7. Risks & Decision Points

| # | Risk | Mitigation |
|---|---|---|
| R1 | Keyring absent on Linux CI | In-memory fake backend via pytest fixture. |
| R2 | Thread races on SQLite writes | WAL mode + `PRAGMA busy_timeout = 5000`. Single writer thread for audit_log. |
| R3 | HyperliquidClient blocking calls in async context | `asyncio.to_thread()` wrappers in routers; never await an SDK call directly. |
| R4 | Partial kill-switch (cancel succeeds, close fails) | Per-step audit logging so operator has clean recovery path. Report flags errors; operator can manually finish. |
| R5 | Shadow client testnet drift from mainnet | Expected — shadow is for catching bugs, not expecting parity. Divergence alert fires for user awareness, not auto-halt. |
| R6 | Audit log growth unbounded | Add periodic archival to Parquet in a later phase; for now SQLite handles GBs fine. |
| R7 | `.env` fallback for keys in dev → production | `DEV_MODE` env var required; app refuses to start with `.env` key + `USE_TESTNET=false`. |

**Open decisions:**

1. **Sync vs async for TradeEngineService.** Default: sync with ThreadPoolExecutor (simpler, matches Hyperliquid SDK's sync nature). Revisit if we hit scalability issues.
2. **Kill-switch "reset" requirement.** Default: require all positions flat + explicit confirmation before reset. Prevents half-killed state.
3. **Manual order placement via API.** Default: yes, but audited as `source='user_manual'` so strategy attribution stays clean.

---

## 8. Success Criteria

End of Phase 2, all true:

1. `curl POST /vault/store -d '{"wallet_address":"0x...","private_key":"..."}'` stores a key to OS keychain. Disk has no plaintext.
2. `curl POST /slots -d '{...}' && curl POST /slots/{id}/start` begins trading. `curl /audit?slot_id=...` shows per-tick decision entries.
3. Mainnet slot running on ETH 1h EMA crossover for 1 hour on testnet — emits ≥ 60 `decision_emitted` audit rows.
4. `curl POST /killswitch/activate -d '{"confirmation":"KILL"}'` — within 2s, every position is flat, every slot disabled, audit has per-step entries, WS broadcast received.
5. `curl GET /universe | jq '.[] | .category' | sort -u` returns `["commodity","crypto","fx","index","outcome","stock"]` after refresh.
6. `curl GET /audit.csv > audit.csv` downloads full history.
7. Shadow-enabled slot emits `shadow_divergence` events when the two clients disagree.
8. Tests cover: 90% statement coverage on `backend/services/`, every API route has a happy-path + error-path test.
9. CI green in < 2 min.

---

## 9. Time Estimate

| Commit | Scope | Days |
|---|---|---|
| P2.1 UniverseManager | + markets schema seed | 1.5 |
| P2.2 app_db + migrations | Full schema + triggers | 1.0 |
| P2.3 KeyVault + /vault | Keychain integration | 1.0 |
| P2.4 AuditService + /audit | Append-only SQL + CSV | 1.0 |
| P2.5 KillSwitch + /killswitch | Cancel/close cascade | 1.0 |
| P2.6 TradeEngineService | Multi-slot orchestration | 2.0 |
| P2.7 Slots/Orders/Stream APIs | REST + WS | 1.5 |
| P2.8 ShadowClient | Fork + divergence detection | 1.0 |
| **Total** | | **10 days ≈ 2 weeks** |

---

## 10. Out of Scope (deferred)

- **UI wiring of these APIs** — Phase 3.
- **Chart integration with orders** — Phase 5.
- **Outcome-slot parity** — Phase 6 (parallel SlotRunner variant for HIP-4).
- **ML-backed slots** — Phase 10 (just `strategy: 'ml:<model_id>'` string once registry exists).
- **Backtest integration** — Phase 7 (BacktestEngine wraps the same `engine.py` but with ExchangeShim).
- **`bot.py` migration to TradeEngine** — can happen anytime; not blocking.
- **`dashboard.py` retirement** — Phase 12.

---

## 11. Dependencies On Other Phases

- **Needs Phase 1 done:** `data_catalog.query_candles()` is how SlotRunner builds `ctx.candles_df`.
- **Unblocks:** Phase 3 UI (every screen hits APIs from here). Phase 5 chart-to-order (uses `/orders`). Phase 6 outcome workspace (uses `UniverseManager` for outcome markets + `SlotRunner` for outcome slots). Phase 7 backtest (uses the same `engine.py` through a different executor). Phase 11 slot 2.0 (layers per-slot filters on top of SlotRunner).
