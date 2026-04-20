-- 002_markups.sql — layout + markup storage for the chart workspace.

CREATE TABLE IF NOT EXISTS layouts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    symbol          TEXT,
    interval        TEXT,
    indicators_json TEXT,
    panes_json      TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS markups (
    id           TEXT PRIMARY KEY,
    layout_id    TEXT REFERENCES layouts(id) ON DELETE CASCADE,
    symbol       TEXT NOT NULL,
    interval     TEXT,
    tool_id      TEXT NOT NULL,          -- 'horizontal_line' | 'trendline' | 'long_position' | ...
    payload_json TEXT NOT NULL,          -- tool-specific data
    style_json   TEXT,
    z            INTEGER DEFAULT 0,
    locked       INTEGER DEFAULT 0,
    hidden       INTEGER DEFAULT 0,
    state        TEXT DEFAULT 'draft',   -- 'draft' | 'pending' | 'active' | 'closed' | 'cancelled'
    order_id     TEXT,                   -- set when state >= 'pending'
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_markups_symbol_interval ON markups(symbol, interval);
CREATE INDEX IF NOT EXISTS idx_markups_layout ON markups(layout_id);

INSERT OR IGNORE INTO schema_version(version) VALUES (2);
