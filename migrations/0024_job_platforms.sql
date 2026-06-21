-- 0024_job_platforms.sql
-- Per-country job-platform catalog for the multi-platform job hunt. A daily
-- discovery orchestrator (assistant/job/platforms/discovery.py) figures out the
-- best job boards for each country (LLM proposes → live JSearch sampling
-- validates) and upserts them here. The dashboard reads this to populate a
-- per-country platform multi-select; the search then filters JSearch results to
-- the publishers the user picked.
--
-- Shared across all users (like content_creators) — there is no user_id; the
-- "best boards for Switzerland" don't differ per tenant.
--
-- The agents job module (Service B) also applies this idempotently at startup in
-- assistant/job/platforms/catalog.py::_DDL — this migration mirrors that for
-- Service A parity.

CREATE TABLE IF NOT EXISTS job_platforms (
    id            SERIAL PRIMARY KEY,
    country_code  VARCHAR(2)   NOT NULL,                       -- ISO 3166-1 alpha-2 (matches countries.py)
    platform_key  VARCHAR(80)  NOT NULL,                       -- slug: 'linkedin', 'jobs_ch', 'gaijinpot'
    display_name  TEXT         NOT NULL,
    domain        TEXT,                                        -- publisher domain used to match JSearch results
    source_kind   VARCHAR(20)  NOT NULL DEFAULT 'jsearch',     -- 'jsearch' | 'adapter'
    adapter_host  TEXT,                                        -- RapidAPI host when source_kind='adapter'
    rank          SMALLINT     NOT NULL DEFAULT 0,             -- higher = surfaced first
    available     BOOLEAN      NOT NULL DEFAULT TRUE,          -- confirmed by live JSearch sampling
    needs_key     BOOLEAN      NOT NULL DEFAULT FALSE,         -- dedicated source needs an API key we don't have
    last_checked  TIMESTAMPTZ,
    UNIQUE (country_code, platform_key)
);

CREATE INDEX IF NOT EXISTS idx_jp_country ON job_platforms (country_code, rank DESC);
