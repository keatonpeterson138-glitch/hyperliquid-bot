-- 008_plaid.sql — Plaid linked-items + account ledger.
-- One `plaid_items` row per institution the user connects (each holds an
-- access_token). One `plaid_accounts` row per account within an item — the
-- UI lets the user toggle ``tracked`` so the Balances refresh only pulls
-- accounts they care about.

CREATE TABLE IF NOT EXISTS plaid_items (
    id                TEXT PRIMARY KEY,                  -- 'pli_<uuid>'
    plaid_item_id     TEXT NOT NULL UNIQUE,              -- opaque id from Plaid
    access_token      TEXT NOT NULL,                     -- persists indefinitely unless revoked
    institution_id    TEXT,
    institution_name  TEXT,
    environment       TEXT NOT NULL DEFAULT 'production',
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plaid_accounts (
    id            TEXT PRIMARY KEY,                      -- 'pla_<uuid>'
    item_id       TEXT NOT NULL REFERENCES plaid_items(id) ON DELETE CASCADE,
    plaid_account_id TEXT NOT NULL,                      -- opaque per-account id
    name          TEXT,
    official_name TEXT,
    type          TEXT,                                  -- 'investment' | 'depository' | 'brokerage' | ...
    subtype       TEXT,                                  -- 'brokerage' | '401k' | 'ira' | 'checking' | ...
    mask          TEXT,                                  -- last 4 of the account number (for display)
    broker_label  TEXT,                                  -- maps to the 'broker' field in `balances` table
    tracked       INTEGER NOT NULL DEFAULT 1,            -- 0/1 — user can untoggle to stop refreshing
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_id, plaid_account_id)
);

CREATE INDEX IF NOT EXISTS idx_plaid_accounts_item ON plaid_accounts(item_id);
CREATE INDEX IF NOT EXISTS idx_plaid_accounts_tracked ON plaid_accounts(tracked);

INSERT OR IGNORE INTO schema_version(version) VALUES (8);
