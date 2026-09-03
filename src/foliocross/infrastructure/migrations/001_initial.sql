CREATE TABLE books (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    source_format TEXT NOT NULL,
    source_lang TEXT NOT NULL DEFAULT 'auto',
    target_lang TEXT NOT NULL DEFAULT 'zh-CN',
    original_path TEXT NOT NULL,
    stored_source_path TEXT NOT NULL,
    working_source_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id),
    status TEXT NOT NULL,
    desired_state TEXT NOT NULL DEFAULT 'pause',
    stage TEXT NOT NULL DEFAULT 'imported',
    preset TEXT NOT NULL DEFAULT 'steady',
    config_json TEXT NOT NULL,
    total_segments INTEGER NOT NULL DEFAULT 0,
    completed_segments INTEGER NOT NULL DEFAULT 0,
    current_message TEXT NOT NULL DEFAULT '',
    error_code TEXT,
    error_message TEXT,
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL,
    actual_cost REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    heartbeat_at TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE job_steps (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY(job_id, name)
);

CREATE TABLE chapters (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    locator_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(book_id, chapter_index)
);

CREATE TABLE segments (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    locked INTEGER NOT NULL DEFAULT 0,
    locator_json TEXT NOT NULL DEFAULT '{}',
    markers_json TEXT NOT NULL DEFAULT '[]',
    quality_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(chapter_id, segment_index)
);

CREATE TABLE segment_revisions (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    origin TEXT NOT NULL,
    model TEXT,
    instruction TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(segment_id, version)
);

CREATE TABLE glossary_terms (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    term_type TEXT NOT NULL DEFAULT 'term',
    reading TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    frequency INTEGER NOT NULL DEFAULT 1,
    first_chapter INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'approved',
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, source)
);

CREATE TABLE review_issues (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    segment_id TEXT REFERENCES segments(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    suggestion TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE llm_requests (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    error_code TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE usage_events (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES llm_requests(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cache_hit_tokens INTEGER NOT NULL,
    cost REAL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_jobs_book ON jobs(book_id, created_at DESC);
CREATE INDEX idx_segments_chapter ON segments(chapter_id, segment_index);
CREATE INDEX idx_glossary_job ON glossary_terms(job_id, source);
CREATE INDEX idx_issues_job ON review_issues(job_id, status);
CREATE INDEX idx_usage_job ON usage_events(job_id, created_at);
CREATE INDEX idx_events_job ON events(job_id, seq);
