CREATE TABLE glossary_candidates (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    term_type TEXT NOT NULL DEFAULT 'term',
    reading TEXT NOT NULL DEFAULT '',
    frequency INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 0,
    first_chapter INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(job_id, source, target)
);

CREATE INDEX idx_glossary_candidates_source ON glossary_candidates(job_id, source);
