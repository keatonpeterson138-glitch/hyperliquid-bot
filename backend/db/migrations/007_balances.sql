-- 007_balances.sql — per-broker EoD balance ledger (Phase 13 ext).
-- One row per (broker, asof) snapshot. The Balances page shows the
-- latest per broker + summary over all brokers.

CREATE TABLE IF NOT EXISTS balances (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    broker         TEXT NOT NULL,            -- 'hyperliquid' | 'coinbase' | 'kraken' | 'robinhood' | 'etrade' | 'fidelity' | 'schwab' | other
    asof           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    equity_usd     REAL NOT NULL,
    cash_usd       REAL,
    buying_power   REAL,
    unrealised_pnl REAL,
    realised_pnl_today REAL,
    source_note    TEXT,                      -- 'auto' | 'manual' | error detail
    raw_json       TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_balances_broker ON balances(broker);
CREATE INDEX IF NOT EXISTS idx_balances_asof ON balances(asof);

INSERT OR IGNORE INTO schema_version(version) VALUES (7);
