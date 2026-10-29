ALTER TABLE artifacts ADD COLUMN available INTEGER NOT NULL DEFAULT 1;
CREATE TABLE export_publications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    format TEXT NOT NULL,
    stage_path TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    delivery_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TEXT NOT NULL
);
