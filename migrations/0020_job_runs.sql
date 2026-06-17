-- 0020_job_runs.sql
-- Per-user job-run lifecycle so a run's status survives a service restart and a
-- failure is never silent. A row is created 'running' when a run starts and
-- transitioned to 'completed' / 'failed' when it ends; a 'running' row left
-- behind by a killed process (e.g. a deploy mid-run) is reported as
-- 'interrupted' by the API once it goes stale.
-- The agents job module also applies this idempotently in db.py::_DDL at startup.

CREATE TABLE IF NOT EXISTS job_runs (
    id            SERIAL PRIMARY KEY,
    user_id       UUID            NOT NULL,
    status        VARCHAR(20)     NOT NULL DEFAULT 'running',
    started_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    error         TEXT,
    countries     TEXT[],
    strong_count  INT             NOT NULL DEFAULT 0,
    good_count    INT             NOT NULL DEFAULT 0,
    saved_count   INT             NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jr_user ON job_runs (user_id, started_at DESC);
