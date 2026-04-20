-- 001_initial.sql — initial schema for app.db

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Markets (filled by UniverseManager from Hyperliquid Info API + HIP-3 dexes + HIP-4)
CREATE TABLE IF NOT EXISTS markets (
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
    resolution_date TIMESTAMP,
    bounds_json     TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    first_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_markets_kind_active ON markets(kind, active);
CREATE INDEX IF NOT EXISTS idx_markets_category    ON markets(category);

CREATE TABLE IF NOT EXISTS market_tags (
    market_id TEXT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (market_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_market_tags_tag ON market_tags(tag);

-- Append-only audit log for every order / kill-switch / slot lifecycle event.
CREATE TABLE IF NOT EXISTS audit_log (
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
CREATE INDEX IF NOT EXISTS idx_audit_ts      ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_symbol  ON audit_log(symbol);
CREATE INDEX IF NOT EXISTS idx_audit_slot    ON audit_log(slot_id);
CREATE INDEX IF NOT EXISTS idx_audit_type    ON audit_log(event_type);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- Slots (trading configurations)
CREATE TABLE IF NOT EXISTS slots (
    id                     TEXT PRIMARY KEY,
    kind                   TEXT NOT NULL CHECK (kind IN ('perp','outcome')),
    symbol                 TEXT NOT NULL,
    interval               TEXT,
    strategy               TEXT NOT NULL,
    strategy_params_json   TEXT NOT NULL DEFAULT '{}',
    size_usd               REAL NOT NULL,
    leverage               INTEGER,
    stop_loss_pct          REAL,
    take_profit_pct        REAL,
    enabled                INTEGER NOT NULL DEFAULT 0,
    shadow_enabled         INTEGER NOT NULL DEFAULT 0,
    trailing_sl            INTEGER DEFAULT 0,
    mtf_enabled            INTEGER DEFAULT 1,
    regime_filter          INTEGER DEFAULT 0,
    atr_stops              INTEGER DEFAULT 0,
    loss_cooldown          INTEGER DEFAULT 0,
    volume_confirm         INTEGER DEFAULT 0,
    rsi_guard              INTEGER DEFAULT 0,
    rsi_guard_low          REAL DEFAULT 30.0,
    rsi_guard_high         REAL DEFAULT 70.0,
    ml_model_id            TEXT,
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_slots_enabled ON slots(enabled);

CREATE TABLE IF NOT EXISTS slot_state (
    slot_id              TEXT PRIMARY KEY REFERENCES slots(id) ON DELETE CASCADE,
    last_tick_at         TIMESTAMP,
    last_signal          TEXT,
    last_decision_action TEXT,
    current_position     TEXT,
    entry_price          REAL,
    position_size_usd    REAL,
    open_order_ids_json  TEXT
);

INSERT OR IGNORE INTO schema_version(version) VALUES (1);
