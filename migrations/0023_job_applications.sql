-- 0023_job_applications.sql
-- AI-generated job applications for the Job hunt "Apply" flow. Each row is one
-- application per (user, match): an AI-written cover letter merged with the
-- user's original CV/certificate PDFs into a single PDF, stored inline as bytea
-- so it survives restarts and the user can revisit and refine it via feedback.
--
-- The agents job module (Service B) also applies this idempotently at startup in
-- assistant/job/db.py::_DDL — this migration mirrors that for Service A parity.

-- The full scraped job description, needed by the application agent. Older rows
-- have NULL and fall back to ai_summary + flags at application time.
ALTER TABLE job_matches ADD COLUMN IF NOT EXISTS description TEXT;

CREATE TABLE IF NOT EXISTS job_applications (
    id               SERIAL PRIMARY KEY,
    user_id          UUID            NOT NULL,
    match_id         INT             NOT NULL,
    status           VARCHAR(20)     NOT NULL DEFAULT 'generating',  -- generating | ready | failed
    pdf_bytes        BYTEA,
    cover_letter     TEXT,
    manifest         JSONB,
    feedback_history JSONB           NOT NULL DEFAULT '[]'::jsonb,
    error            TEXT,
    iterations       INT             NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, match_id)
);

CREATE INDEX IF NOT EXISTS idx_ja_user  ON job_applications (user_id);
CREATE INDEX IF NOT EXISTS idx_ja_match ON job_applications (user_id, match_id);
