-- 004_models.sql — trained-model registry (Phase 10).

CREATE TABLE IF NOT EXISTS models (
    id                TEXT PRIMARY KEY,
    family            TEXT NOT NULL,      -- 'xgb_cls' | 'logreg' | 'rf_cls'
    version           TEXT NOT NULL,      -- timestamp-based
    path              TEXT NOT NULL,      -- directory under data/models/
    features_json     TEXT,
    label             TEXT,
    metrics_json      TEXT,
    config_json       TEXT,
    promoted_slot_id  TEXT REFERENCES slots(id) ON DELETE SET NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_models_family ON models(family);
CREATE INDEX IF NOT EXISTS idx_models_created ON models(created_at);

INSERT OR IGNORE INTO schema_version(version) VALUES (4);
