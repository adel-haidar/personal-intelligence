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
    status            VARCHAR(30)     NOT NULL DEFAULT 'new',
    applied_at        TIMESTAMPTZ,
    notes             TEXT,
    user_id           UUID
);
-- Per-user multi-tenancy: the same job_url can belong to multiple users, so
-- uniqueness is (user_id, job_url), not job_url alone. Idempotent for tables
-- created before this (mirrors migrations/0009).
ALTER TABLE job_matches ADD COLUMN IF NOT EXISTS user_id UUID;
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
                    disqualifier_flag, rejection_reason, ai_summary, user_id
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21::uuid)
                ON CONFLICT (user_id, job_url) DO UPDATE SET
                    match_score   = EXCLUDED.match_score,
                    ai_summary    = EXCLUDED.ai_summary,
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
