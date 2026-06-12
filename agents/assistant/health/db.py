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
    UNIQUE (recorded_at, metric_type, source)
);
CREATE INDEX IF NOT EXISTS idx_hm_type_time ON health_metrics (metric_type, recorded_at DESC);
-- NOTE: no expression index on date_trunc('day', recorded_at) — date_trunc on
-- timestamptz is STABLE, not IMMUTABLE, so Postgres rejects it in an index
-- expression (42P17) and the whole multi-statement DDL rolls back with it.
CREATE INDEX IF NOT EXISTS idx_hm_source_time ON health_metrics (source, recorded_at DESC);
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


async def bulk_insert(pool: asyncpg.Pool, metrics: list[HealthMetric]) -> int:
    """Insert metrics, skipping duplicates on (recorded_at, metric_type, source)."""
    if not metrics:
        return 0
    inserted = 0
    async with pool.acquire() as conn:
        for m in metrics:
            tag = await conn.execute(
                """
                INSERT INTO health_metrics (recorded_at, metric_type, value, unit, source)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (recorded_at, metric_type, source) DO NOTHING
                """,
                m.recorded_at, m.metric_type, m.value, m.unit, m.source,
            )
            if tag == "INSERT 0 1":
                inserted += 1
    return inserted


async def insert_one(pool: asyncpg.Pool, metric: HealthMetric) -> bool:
    async with pool.acquire() as conn:
        tag = await conn.execute(
            """
            INSERT INTO health_metrics (recorded_at, metric_type, value, unit, source)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (recorded_at, metric_type, source) DO NOTHING
            """,
            metric.recorded_at, metric.metric_type, metric.value, metric.unit, metric.source,
        )
        return tag == "INSERT 0 1"


async def fetch_metrics(
    pool: asyncpg.Pool,
    metric_type: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, recorded_at, metric_type, value, unit, source
            FROM health_metrics
            WHERE metric_type = $1 AND recorded_at >= $2 AND recorded_at < $3
            ORDER BY recorded_at ASC
            """,
            metric_type, start, end,
        )
        return [dict(r) for r in rows]


async def fetch_latest_metric(
    pool: asyncpg.Pool,
    metric_type: str,
    before: datetime,
    lookback_days: int = 2,
) -> Optional[dict]:
    """Return the most recent row for metric_type within lookback_days before `before`."""
    start = before - timedelta(days=lookback_days)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, recorded_at, metric_type, value, unit, source
            FROM health_metrics
            WHERE metric_type = $1 AND recorded_at >= $2 AND recorded_at < $3
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            metric_type, start, before,
        )
        return dict(row) if row else None


async def fetch_source_days(
    pool: asyncpg.Pool,
    sources: list[str],
    end: datetime,
    days: int = 60,
) -> list[date]:
    """Return the distinct days (ascending) that have any data from the given sources."""
    start = end - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT (recorded_at AT TIME ZONE 'UTC')::date AS day
            FROM health_metrics
            WHERE source = ANY($1) AND recorded_at >= $2 AND recorded_at < $3
            ORDER BY day ASC
            """,
            sources, start, end,
        )
        return [r["day"] for r in rows]


async def fetch_trends(
    pool: asyncpg.Pool,
    metric_types: list[str],
    days: int,
) -> dict[str, list[dict]]:
    """Return daily time series for each metric_type over last N days."""
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
                WHERE metric_type = $1 AND recorded_at >= $2
                GROUP BY day
                ORDER BY day ASC
                """,
                mt, cutoff,
            )
            result[mt] = [
                {"date": r["day"].date().isoformat(), "value": float(r["value"])}
                for r in rows
            ]
    return result
