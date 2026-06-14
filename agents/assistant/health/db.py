import logging
from datetime import date, datetime, timedelta
from typing import Optional

import asyncpg

from assistant.health.models import HealthMetric

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS health_metrics (
    id          SERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL,
    metric_type VARCHAR(40)  NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        VARCHAR(20)  NOT NULL,
    source      VARCHAR(30)  NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id     UUID,
    UNIQUE (user_id, recorded_at, metric_type, source)
);
-- Per-user multi-tenancy: ensure user_id exists and uniqueness is per-user, even
-- on tables created before this (mirrors migrations/0008). Two users may record
-- the same (recorded_at, metric_type, source) without colliding.
ALTER TABLE health_metrics ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE health_metrics DROP CONSTRAINT IF EXISTS health_metrics_recorded_at_metric_type_source_key;
CREATE INDEX IF NOT EXISTS idx_hm_type_time ON health_metrics (metric_type, recorded_at DESC);
-- NOTE: no expression index on date_trunc('day', recorded_at) — date_trunc on
-- timestamptz is STABLE, not IMMUTABLE, so Postgres rejects it in an index
-- expression (42P17) and the whole multi-statement DDL rolls back with it.
CREATE INDEX IF NOT EXISTS idx_hm_source_time ON health_metrics (source, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_hm_user_type_time ON health_metrics (user_id, metric_type, recorded_at DESC);
"""

# The per-user unique constraint is added separately: ADD CONSTRAINT has no
# IF NOT EXISTS, so a re-run would error inside the multi-statement _DDL above.
_DDL_CONSTRAINT = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_health_user_metric') THEN
        ALTER TABLE health_metrics
            ADD CONSTRAINT uq_health_user_metric UNIQUE (user_id, recorded_at, metric_type, source);
    END IF;
END $$;
"""

_pool: Optional[asyncpg.Pool] = None


async def init_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        # Publish the global only after the schema is verified — otherwise a DDL
        # failure leaves a half-initialized pool that every later request reuses
        # while the table doesn't exist.
        pool = await asyncpg.create_pool(database_url)
        try:
            async with pool.acquire() as conn:
                await conn.execute(_DDL)
                await conn.execute(_DDL_CONSTRAINT)
        except Exception:
            await pool.close()
            raise
        _pool = pool
        logger.info("Health DB pool initialized and schema verified")
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Health DB pool not initialized")
    return _pool


async def bulk_insert(pool: asyncpg.Pool, metrics: list[HealthMetric], *, user_id: str) -> int:
    """Insert metrics for a user, skipping duplicates. # MUST SCOPE BY USER"""
    assert user_id, "user_id required"
    if not metrics:
        return 0
    inserted = 0
    async with pool.acquire() as conn:
        for m in metrics:
            tag = await conn.execute(
                """
                INSERT INTO health_metrics (recorded_at, metric_type, value, unit, source, user_id)
                VALUES ($1, $2, $3, $4, $5, $6::uuid)
                ON CONFLICT (user_id, recorded_at, metric_type, source) DO NOTHING
                """,
                m.recorded_at, m.metric_type, m.value, m.unit, m.source, user_id,
            )
            if tag == "INSERT 0 1":
                inserted += 1
    return inserted


async def insert_one(pool: asyncpg.Pool, metric: HealthMetric, *, user_id: str) -> bool:
    assert user_id, "user_id required"  # MUST SCOPE BY USER
    async with pool.acquire() as conn:
        tag = await conn.execute(
            """
            INSERT INTO health_metrics (recorded_at, metric_type, value, unit, source, user_id)
            VALUES ($1, $2, $3, $4, $5, $6::uuid)
            ON CONFLICT (user_id, recorded_at, metric_type, source) DO NOTHING
            """,
            metric.recorded_at, metric.metric_type, metric.value, metric.unit, metric.source, user_id,
        )
        return tag == "INSERT 0 1"


async def fetch_metrics(
    pool: asyncpg.Pool,
    metric_type: str,
    start: datetime,
    end: datetime,
    *,
    user_id: str,
) -> list[dict]:
    assert user_id, "user_id required"  # MUST SCOPE BY USER
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, recorded_at, metric_type, value, unit, source
            FROM health_metrics
            WHERE user_id = $4::uuid AND metric_type = $1 AND recorded_at >= $2 AND recorded_at < $3
            ORDER BY recorded_at ASC
            """,
            metric_type, start, end, user_id,
        )
        return [dict(r) for r in rows]


async def fetch_latest_metric(
    pool: asyncpg.Pool,
    metric_type: str,
    before: datetime,
    lookback_days: int = 2,
    *,
    user_id: str,
) -> Optional[dict]:
    """Return the most recent row for metric_type within lookback_days before `before`.
    # MUST SCOPE BY USER"""
    assert user_id, "user_id required"
    start = before - timedelta(days=lookback_days)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, recorded_at, metric_type, value, unit, source
            FROM health_metrics
            WHERE user_id = $4::uuid AND metric_type = $1 AND recorded_at >= $2 AND recorded_at < $3
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            metric_type, start, before, user_id,
        )
        return dict(row) if row else None


async def fetch_source_days(
    pool: asyncpg.Pool,
    sources: list[str],
    end: datetime,
    days: int = 60,
    *,
    user_id: str,
) -> list[date]:
    """Return the distinct days (ascending) that have any data from the given sources.
    # MUST SCOPE BY USER"""
    assert user_id, "user_id required"
    start = end - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT (recorded_at AT TIME ZONE 'UTC')::date AS day
            FROM health_metrics
            WHERE user_id = $4::uuid AND source = ANY($1) AND recorded_at >= $2 AND recorded_at < $3
            ORDER BY day ASC
            """,
            sources, start, end, user_id,
        )
        return [r["day"] for r in rows]


async def fetch_trends(
    pool: asyncpg.Pool,
    metric_types: list[str],
    days: int,
    *,
    user_id: str,
) -> dict[str, list[dict]]:
    """Return daily time series for each metric_type over last N days. # MUST SCOPE BY USER"""
    assert user_id, "user_id required"
    cutoff = datetime.utcnow() - timedelta(days=days)
    result: dict[str, list[dict]] = {mt: [] for mt in metric_types}

    async with pool.acquire() as conn:
        for mt in metric_types:
            rows = await conn.fetch(
                """
                SELECT
                    date_trunc('day', recorded_at AT TIME ZONE 'UTC') AS day,
                    AVG(value) AS value
                FROM health_metrics
                WHERE user_id = $3::uuid AND metric_type = $1 AND recorded_at >= $2
                GROUP BY day
                ORDER BY day ASC
                """,
                mt, cutoff, user_id,
            )
            result[mt] = [
                {"date": r["day"].date().isoformat(), "value": float(r["value"])}
                for r in rows
            ]
    return result
