-- 005_notes.sql — interactive notes panel + notifications center (Phase 13).

CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    body_md      TEXT NOT NULL DEFAULT '',
    tags_json    TEXT,
    linked_layout_id TEXT REFERENCES layouts(id) ON DELETE SET NULL,
    linked_backtest_id TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);

CREATE TABLE IF NOT EXISTS note_attachments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id    TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,
    kind       TEXT NOT NULL,              -- 'screenshot' | 'file' | 'widget'
    meta_json  TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_note_attach_note ON note_attachments(note_id);

CREATE TABLE IF NOT EXISTS notification_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,             -- 'fill' | 'kill_switch' | 'backtest_done' | 'divergence' | 'data_done'
    source       TEXT,
    title        TEXT NOT NULL,
    body         TEXT,
    payload_json TEXT,
    read_at      TIMESTAMP,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notif_created ON notification_events(created_at);
CREATE INDEX IF NOT EXISTS idx_notif_unread ON notification_events(read_at);

INSERT OR IGNORE INTO schema_version(version) VALUES (5);
