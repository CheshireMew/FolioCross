CREATE TABLE projection_revisions (scope_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
CREATE TRIGGER revision_llm_requests_insert AFTER INSERT ON llm_requests
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_llm_requests_update AFTER UPDATE ON llm_requests
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_llm_requests_delete AFTER DELETE ON llm_requests
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_segments_insert AFTER INSERT ON segments
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES ((SELECT book_id FROM chapters WHERE id=NEW.chapter_id),1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_segments_update AFTER UPDATE ON segments
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES ((SELECT book_id FROM chapters WHERE id=NEW.chapter_id),1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_segments_delete AFTER DELETE ON segments
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES ((SELECT book_id FROM chapters WHERE id=OLD.chapter_id),1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_chapters_insert AFTER INSERT ON chapters
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.book_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_chapters_update AFTER UPDATE ON chapters
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.book_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_chapters_delete AFTER DELETE ON chapters
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.book_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_glossary_terms_insert AFTER INSERT ON glossary_terms
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_glossary_terms_update AFTER UPDATE ON glossary_terms
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_glossary_terms_delete AFTER DELETE ON glossary_terms
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_review_issues_insert AFTER INSERT ON review_issues
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_review_issues_update AFTER UPDATE ON review_issues
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_review_issues_delete AFTER DELETE ON review_issues
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_usage_events_insert AFTER INSERT ON usage_events
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_usage_events_update AFTER UPDATE ON usage_events
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_usage_events_delete AFTER DELETE ON usage_events
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_artifacts_insert AFTER INSERT ON artifacts
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_artifacts_update AFTER UPDATE ON artifacts
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_artifacts_delete AFTER DELETE ON artifacts
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_job_steps_insert AFTER INSERT ON job_steps
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_job_steps_update AFTER UPDATE ON job_steps
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_job_steps_delete AFTER DELETE ON job_steps
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_background_operations_insert AFTER INSERT ON background_operations
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_background_operations_update AFTER UPDATE ON background_operations
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (NEW.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
CREATE TRIGGER revision_background_operations_delete AFTER DELETE ON background_operations
BEGIN
    INSERT INTO projection_revisions(scope_id,revision) VALUES (OLD.job_id,1)
    ON CONFLICT(scope_id) DO UPDATE SET revision=revision+1;
END;
