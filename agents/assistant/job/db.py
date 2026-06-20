import json
import logging
from typing import Optional

import asyncpg

from assistant.job.models import JobListing, MatchResult

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS job_matches (
    id                SERIAL PRIMARY KEY,
    run_timestamp     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    platform          VARCHAR(50)     NOT NULL,
    title             TEXT            NOT NULL,
    company           TEXT            NOT NULL,
    location          TEXT            NOT NULL,
    country           VARCHAR(50)     NOT NULL,
    job_url           TEXT            NOT NULL,
    posted_date       DATE,
    salary_raw        TEXT,
    salary_min_local  NUMERIC(12,2),
    salary_max_local  NUMERIC(12,2),
    currency          VARCHAR(10),
    remote_type       VARCHAR(20),
    match_score       SMALLINT        NOT NULL CHECK (match_score BETWEEN 0 AND 100),
    match_tier        VARCHAR(20)     NOT NULL,
    tech_flags        TEXT[],
    domain_flags      TEXT[],
    positive_flags    TEXT[],
    disqualifier_flag TEXT,
    rejection_reason  TEXT,
    ai_summary        TEXT,
    description       TEXT,
    status            VARCHAR(30)     NOT NULL DEFAULT 'new',
    applied_at        TIMESTAMPTZ,
    notes             TEXT,
    user_id           UUID
);
-- Per-user multi-tenancy: the same job_url can belong to multiple users, so
-- uniqueness is (user_id, job_url), not job_url alone. Idempotent for tables
-- created before this (mirrors migrations/0009).
ALTER TABLE job_matches ADD COLUMN IF NOT EXISTS user_id UUID;
-- The full scraped job description, needed by the application agent. Older rows
-- have NULL here and fall back to ai_summary + flags at application time.
ALTER TABLE job_matches ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE job_matches DROP CONSTRAINT IF EXISTS job_matches_job_url_key;
CREATE INDEX IF NOT EXISTS idx_jm_score   ON job_matches (match_score DESC);
CREATE INDEX IF NOT EXISTS idx_jm_country ON job_matches (country);
CREATE INDEX IF NOT EXISTS idx_jm_tier    ON job_matches (match_tier);
CREATE INDEX IF NOT EXISTS idx_jm_run     ON job_matches (run_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jm_status  ON job_matches (status);
CREATE INDEX IF NOT EXISTS idx_jm_user    ON job_matches (user_id);

-- Per-user run lifecycle so a run's status survives a service restart and a
-- failure is never silent. A row is created 'running' when a run starts and
-- transitioned to 'completed' / 'failed' when it ends. A 'running' row left
-- behind by a killed process is reported as 'interrupted' once it goes stale.
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

-- One AI-generated job application per (user, match). The merged PDF (cover
-- letter + the user's original CV/certificate files) is stored inline as bytea
-- so it survives restarts and the user can revisit it. Generation runs in the
-- background: a row starts 'generating' and becomes 'ready' or 'failed'.
-- Mirrors migrations/0010_job_applications.sql.
CREATE TABLE IF NOT EXISTS job_applications (
    id               SERIAL PRIMARY KEY,
    user_id          UUID            NOT NULL,
    match_id         INT             NOT NULL,
    status           VARCHAR(20)     NOT NULL DEFAULT 'generating',
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
"""

# ADD CONSTRAINT has no IF NOT EXISTS, so the per-user unique is applied separately.
_DDL_CONSTRAINT = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_job_user_url') THEN
        ALTER TABLE job_matches ADD CONSTRAINT uq_job_user_url UNIQUE (user_id, job_url);
    END IF;
END $$;
"""

_pool: Optional[asyncpg.Pool] = None


async def init_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(database_url)
        async with _pool.acquire() as conn:
            await conn.execute(_DDL)
            await conn.execute(_DDL_CONSTRAINT)
        logger.info("PostgreSQL pool initialized and schema verified")
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


async def upsert_match(
    pool: asyncpg.Pool, listing: JobListing, result: MatchResult, *, user_id: str
) -> tuple[Optional[int], bool]:
    """Insert or conditionally update a job match for a user.  # MUST SCOPE BY USER

    Returns (row_id, was_saved) where was_saved is True only for a fresh insert
    or a score-bump update.  False means the row already existed and was not
    changed (conflict guard fired or status was protected).
    """
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO job_matches (
                    platform, title, company, location, country, job_url,
                    posted_date, salary_raw, salary_min_local, salary_max_local,
                    currency, remote_type, match_score, match_tier,
                    tech_flags, domain_flags, positive_flags,
                    disqualifier_flag, rejection_reason, ai_summary, user_id,
                    description
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21::uuid,$22)
                ON CONFLICT (user_id, job_url) DO UPDATE SET
                    match_score   = EXCLUDED.match_score,
                    ai_summary    = EXCLUDED.ai_summary,
                    description   = COALESCE(EXCLUDED.description, job_matches.description),
                    run_timestamp = NOW()
                WHERE
                    EXCLUDED.match_score > job_matches.match_score + 5
                    AND job_matches.status NOT IN ('applied','interviewing','withdrawn','rejected')
                RETURNING id
                """,
                listing.platform, listing.title, listing.company,
                listing.location, listing.country, listing.job_url,
                listing.posted_date, listing.salary_raw,
                result.salary_min_local, result.salary_max_local,
                result.currency, result.remote_type,
                result.score, result.match_tier,
                result.tech_flags or [], result.domain_flags or [],
                result.positive_flags or [],
                result.disqualifier_code, result.rejection_reason,
                result.ai_summary, user_id,
                (listing.description or None),
            )
            if row:
                return row["id"], True
            # Conflict resolved without update — already exists, not worth updating
            existing = await conn.fetchrow(
                "SELECT id FROM job_matches WHERE user_id = $1::uuid AND job_url = $2",
                user_id, listing.job_url,
            )
            return (existing["id"] if existing else None), False
        except Exception:
            logger.exception("DB upsert failed for %s", listing.job_url)
            return None, False


async def list_unknown_companies(pool: asyncpg.Pool, *, user_id: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, job_url, platform FROM job_matches "
            "WHERE user_id = $1::uuid AND company IN ('Explore companies', 'Unknown')",
            user_id,
        )
        return [dict(r) for r in rows]


async def update_company(pool: asyncpg.Pool, job_url: str, company: str, *, user_id: str) -> bool:
    async with pool.acquire() as conn:
        tag = await conn.execute(
            "UPDATE job_matches SET company = $1 WHERE user_id = $3::uuid AND job_url = $2",
            company, job_url, user_id,
        )
        return tag == "UPDATE 1"


async def count_all(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM job_matches") or 0


_VALID_STATUSES = frozenset(
    {"new", "reviewing", "applied", "interviewing", "rejected", "withdrawn", "expired"}
)


async def list_matches(
    pool: asyncpg.Pool,
    tier: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    *,
    user_id: str,
) -> list[dict]:
    conditions: list[str] = ["user_id = $1::uuid"]  # MUST SCOPE BY USER
    params: list = [user_id]

    if tier:
        params.append(tier)
        conditions.append(f"match_tier = ${len(params)}")
    if country:
        params.append(country)
        conditions.append(f"country = ${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM job_matches {where} "
            f"ORDER BY match_score DESC, run_timestamp DESC LIMIT ${len(params)}",
            *params,
        )
        return [dict(r) for r in rows]


async def set_status(pool: asyncpg.Pool, match_id: int, status: str, *, user_id: str) -> bool:
    if status not in _VALID_STATUSES:
        return False
    async with pool.acquire() as conn:
        tag = await conn.execute(
            "UPDATE job_matches SET status = $1 WHERE id = $2 AND user_id = $3::uuid",
            status, match_id, user_id,
        )
        return tag == "UPDATE 1"


# A 'running' row older than this with no result is assumed to belong to a
# process that was restarted (e.g. by a deploy) and is reported as interrupted.
_RUN_STALE_AFTER_MINUTES = 15


async def start_run(pool: asyncpg.Pool, *, user_id: str, countries: list[str]) -> int:
    """Open a new run row and supersede any stale 'running' rows for this user.

    Returns the new run id so the caller can finish/fail it later.  # MUST SCOPE BY USER
    """
    async with pool.acquire() as conn:
        # A leftover 'running' row means a previous run never reported back
        # (process killed mid-run). Close it so it can't mask the new one.
        await conn.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = NOW(), "
            "error = 'interrupted — superseded by a newer run' "
            "WHERE user_id = $1::uuid AND status = 'running'",
            user_id,
        )
        return await conn.fetchval(
            "INSERT INTO job_runs (user_id, status, countries) "
            "VALUES ($1::uuid, 'running', $2) RETURNING id",
            user_id, countries,
        )


async def finish_run(
    pool: asyncpg.Pool, run_id: int, *, strong: int, good: int, saved: int
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE job_runs SET status = 'completed', finished_at = NOW(), "
            "strong_count = $2, good_count = $3, saved_count = $4 WHERE id = $1",
            run_id, strong, good, saved,
        )


async def fail_run(pool: asyncpg.Pool, run_id: int, error: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE job_runs SET status = 'failed', finished_at = NOW(), "
            "error = $2 WHERE id = $1",
            run_id, error[:2000],
        )


async def get_latest_run(pool: asyncpg.Pool, *, user_id: str) -> Optional[dict]:
    """The user's most recent run, with stale 'running' rows reported as
    'interrupted' so a killed process surfaces as a real failure.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, started_at, finished_at, error, "
            "strong_count, good_count, saved_count, "
            "EXTRACT(EPOCH FROM (NOW() - started_at)) AS age_seconds "
            "FROM job_runs WHERE user_id = $1::uuid "
            "ORDER BY started_at DESC LIMIT 1",
            user_id,
        )
    if row is None:
        return None
    data = dict(row)
    age_seconds = data.pop("age_seconds", 0) or 0
    if data["status"] == "running" and age_seconds > _RUN_STALE_AFTER_MINUTES * 60:
        data["status"] = "interrupted"
        data["error"] = (
            "The run was interrupted before it finished (the service likely "
            "restarted). Start it again."
        )
    return data


# ── Job applications ─────────────────────────────────────────────────────────
#
# The AI application agent (cover letter + merged original documents) persists
# its result here so the user can close the review window and revisit it later.

# Columns returned for the application metadata view (everything except the
# heavy pdf_bytes blob, which is fetched separately by the /pdf endpoint).
_APP_META_COLS = (
    "id, user_id, match_id, status, cover_letter, manifest, feedback_history, "
    "error, iterations, created_at, updated_at, (pdf_bytes IS NOT NULL) AS has_pdf"
)


def _app_row_to_dict(row: Optional[asyncpg.Record]) -> Optional[dict]:
    """Normalise an application row, decoding JSONB text columns to Python."""
    if row is None:
        return None
    data = dict(row)
    for key in ("manifest", "feedback_history"):
        val = data.get(key)
        if isinstance(val, str):
            try:
                data[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                data[key] = None
    return data


async def get_match(pool: asyncpg.Pool, match_id: int, *, user_id: str) -> Optional[dict]:
    """Fetch a single job match owned by the user.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM job_matches WHERE id = $1 AND user_id = $2::uuid",
            match_id, user_id,
        )
        return dict(row) if row else None


async def create_or_reset_application(
    pool: asyncpg.Pool, match_id: int, *, user_id: str
) -> int:
    """Open (or re-open) the application for a match, set to 'generating'.

    Clears any previous pdf/error so a fresh generation starts cleanly, but
    preserves the feedback_history.  Returns the application id.  # MUST SCOPE BY USER
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO job_applications (user_id, match_id, status)
            VALUES ($1::uuid, $2, 'generating')
            ON CONFLICT (user_id, match_id) DO UPDATE SET
                status     = 'generating',
                pdf_bytes  = NULL,
                error      = NULL,
                updated_at = NOW()
            RETURNING id
            """,
            user_id, match_id,
        )


async def get_application(pool: asyncpg.Pool, app_id: int, *, user_id: str) -> Optional[dict]:
    """Application metadata (no pdf bytes) by id.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_APP_META_COLS} FROM job_applications "
            "WHERE id = $1 AND user_id = $2::uuid",
            app_id, user_id,
        )
        return _app_row_to_dict(row)


async def get_application_by_match(
    pool: asyncpg.Pool, match_id: int, *, user_id: str
) -> Optional[dict]:
    """Application metadata (no pdf bytes) for a match.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_APP_META_COLS} FROM job_applications "
            "WHERE match_id = $1 AND user_id = $2::uuid",
            match_id, user_id,
        )
        return _app_row_to_dict(row)


async def get_application_pdf(
    pool: asyncpg.Pool, app_id: int, *, user_id: str
) -> Optional[bytes]:
    """The merged application PDF bytes, or None if not ready.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT pdf_bytes FROM job_applications "
            "WHERE id = $1 AND user_id = $2::uuid",
            app_id, user_id,
        )
        return bytes(val) if val is not None else None


async def save_application_result(
    pool: asyncpg.Pool,
    app_id: int,
    *,
    user_id: str,
    pdf: bytes,
    cover_letter: str,
    manifest: dict,
    iterations: int,
) -> None:
    """Persist a finished application and mark it 'ready'.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE job_applications SET
                status       = 'ready',
                pdf_bytes    = $3,
                cover_letter = $4,
                manifest     = $5::jsonb,
                iterations   = $6,
                error        = NULL,
                updated_at   = NOW()
            WHERE id = $1 AND user_id = $2::uuid
            """,
            app_id, user_id, pdf, cover_letter,
            json.dumps(manifest, ensure_ascii=False), iterations,
        )


async def fail_application(
    pool: asyncpg.Pool, app_id: int, error: str, *, user_id: str
) -> None:
    """Mark an application 'failed' with a reason.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE job_applications SET status = 'failed', error = $3, "
            "updated_at = NOW() WHERE id = $1 AND user_id = $2::uuid",
            app_id, user_id, (error or "")[:2000],
        )


async def append_feedback(
    pool: asyncpg.Pool, app_id: int, feedback: str, *, user_id: str
) -> bool:
    """Append a user feedback note to the application's history.  # MUST SCOPE BY USER"""
    async with pool.acquire() as conn:
        tag = await conn.execute(
            "UPDATE job_applications SET "
            "feedback_history = feedback_history || $3::jsonb, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2::uuid",
            app_id, user_id, json.dumps([feedback], ensure_ascii=False),
        )
        return tag == "UPDATE 1"
