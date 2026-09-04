ALTER TABLE jobs ADD COLUMN glossary_snapshot_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE jobs ADD COLUMN glossary_snapshot_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN glossary_snapshot_at TEXT;
