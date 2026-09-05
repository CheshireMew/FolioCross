CREATE TABLE background_operations (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    pid INTEGER,
    exit_code INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE UNIQUE INDEX idx_background_operations_active_job
ON background_operations(job_id)
WHERE status IN ('queued', 'running');

CREATE INDEX idx_background_operations_queue
ON background_operations(status, created_at);

ALTER TABLE jobs ADD COLUMN active_elapsed_seconds REAL NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN active_started_at TEXT;
