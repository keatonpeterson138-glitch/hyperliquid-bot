-- 003_orders.sql — bracket-order tracking for chart-to-order (Phase 5.5).

CREATE TABLE IF NOT EXISTS orders (
    id               TEXT PRIMARY KEY,
    slot_id          TEXT REFERENCES slots(id) ON DELETE SET NULL,
    markup_id        TEXT REFERENCES markups(id) ON DELETE SET NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,           -- 'long' | 'short'
    size_usd         REAL NOT NULL,
    leverage         INTEGER,
    entry_type       TEXT NOT NULL,           -- 'market' | 'limit'
    entry_price      REAL,                    -- null for market
    sl_price         REAL,
    tp_price         REAL,
    status           TEXT NOT NULL,           -- 'pending' | 'working' | 'filled' | 'closed' | 'cancelled' | 'rejected'
    exchange_order_id TEXT,                   -- top-level exchange id for the entry leg
    fill_price       REAL,
    source           TEXT DEFAULT 'api',      -- 'api' | 'markup' | 'slot'
    reject_reason    TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_slot ON orders(slot_id);
CREATE INDEX IF NOT EXISTS idx_orders_markup ON orders(markup_id);

-- Each bracket has up to 3 legs: entry, sl, tp. Per-leg exchange ids so we can
-- cancel/modify individually. Some exchanges return one id for the bundle —
-- we store that under the parent `orders.exchange_order_id` in that case.
CREATE TABLE IF NOT EXISTS order_legs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    leg_type         TEXT NOT NULL,           -- 'entry' | 'sl' | 'tp'
    exchange_order_id TEXT,
    price            REAL,
    status           TEXT NOT NULL,           -- 'working' | 'filled' | 'cancelled'
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_order_legs_order ON order_legs(order_id);

INSERT OR IGNORE INTO schema_version(version) VALUES (3);
