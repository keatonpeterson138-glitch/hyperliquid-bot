-- 006_credentials.sql — API keys for third-party providers (Phase 13+).
-- Hyperliquid *private* keys still live in the OS keychain via KeyVault —
-- this table is for less-sensitive per-provider creds (Binance public
-- keys, Alpha Vantage, Polygon, Telegram bot tokens, RSS feeds, etc.).

CREATE TABLE IF NOT EXISTS credentials (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,      -- 'binance' | 'alpha_vantage' | 'polygon' | 'telegram' | 'rss' | ...
    label         TEXT,               -- user-chosen, e.g. 'main trading key'
    api_key       TEXT,               -- masked in all API responses
    api_secret    TEXT,               -- optional for key-only providers
    metadata_json TEXT,               -- extra per-provider config
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_credentials_provider ON credentials(provider);

INSERT OR IGNORE INTO schema_version(version) VALUES (6);
