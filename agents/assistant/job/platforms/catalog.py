"""DB layer for the shared per-country job-platform catalog (job_platforms).

Mirrors migrations/0024_job_platforms.sql and is applied idempotently at startup
so Service B works even before the migration runs on Service A. Shared across
all users — there is no user_id (the best boards for a country don't differ per
tenant), so nothing here is scoped by user.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from assistant.job.platforms.models import Platform

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS job_platforms (
    id            SERIAL PRIMARY KEY,
    country_code  VARCHAR(2)   NOT NULL,
    platform_key  VARCHAR(80)  NOT NULL,
    display_name  TEXT         NOT NULL,
    domain        TEXT,
    source_kind   VARCHAR(20)  NOT NULL DEFAULT 'jsearch',
    adapter_host  TEXT,
    rank          SMALLINT     NOT NULL DEFAULT 0,
    available     BOOLEAN      NOT NULL DEFAULT TRUE,
    needs_key     BOOLEAN      NOT NULL DEFAULT FALSE,
    last_checked  TIMESTAMPTZ,
    UNIQUE (country_code, platform_key)
);
CREATE INDEX IF NOT EXISTS idx_jp_country ON job_platforms (country_code, rank DESC);
"""

_pool: Optional[asyncpg.Pool] = None


async def init_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(database_url)
        async with _pool.acquire() as conn:
            await conn.execute(_DDL)
        logger.info("job_platforms pool initialized and schema verified")
    return _pool


async def upsert_platforms(pool: asyncpg.Pool, platforms: list[Platform]) -> int:
    """Insert or update the given platforms (keyed by country_code + platform_key).

    Returns the number of rows written. `last_checked` is stamped NOW() for every
    upserted row so stale countries can be re-discovered preferentially.
    """
    if not platforms:
        return 0
    now = datetime.now(timezone.utc)
    written = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for p in platforms:
                await conn.execute(
                    """
                    INSERT INTO job_platforms (
                        country_code, platform_key, display_name, domain,
                        source_kind, adapter_host, rank, available, needs_key,
                        last_checked
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (country_code, platform_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        domain       = COALESCE(EXCLUDED.domain, job_platforms.domain),
                        source_kind  = EXCLUDED.source_kind,
                        adapter_host = EXCLUDED.adapter_host,
                        rank         = EXCLUDED.rank,
                        available    = EXCLUDED.available,
                        needs_key    = EXCLUDED.needs_key,
                        last_checked = EXCLUDED.last_checked
                    """,
                    p.country_code.upper(), p.platform_key, p.display_name,
                    p.domain, p.source_kind, p.adapter_host, p.rank,
                    p.available, p.needs_key, now,
                )
                written += 1
    return written


def _row_to_platform(row: asyncpg.Record) -> Platform:
    return Platform(
        country_code=row["country_code"],
        platform_key=row["platform_key"],
        display_name=row["display_name"],
        domain=row["domain"],
        source_kind=row["source_kind"],
        adapter_host=row["adapter_host"],
        rank=row["rank"],
        available=row["available"],
        needs_key=row["needs_key"],
        last_checked=row["last_checked"],
    )


async def list_for_countries(
    pool: asyncpg.Pool, country_codes: list[str]
) -> dict[str, list[Platform]]:
    """Platforms grouped by country code, best-ranked first. Countries with no
    discovered platforms yet are present as empty lists."""
    codes = [c.upper() for c in country_codes if c]
    result: dict[str, list[Platform]] = {c: [] for c in codes}
    if not codes:
        return result
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM job_platforms WHERE country_code = ANY($1::text[]) "
            "ORDER BY country_code, rank DESC, display_name",
            codes,
        )
    for row in rows:
        result.setdefault(row["country_code"], []).append(_row_to_platform(row))
    return result


async def stale_country_codes(
    pool: asyncpg.Pool, all_codes: list[str], fresh_within_hours: int = 24
) -> list[str]:
    """Codes that have NOT been validated within `fresh_within_hours` — i.e. no
    row at all, or the freshest row is older than the cutoff. Used to skip
    re-discovering countries already checked today."""
    codes = [c.upper() for c in all_codes if c]
    if not codes:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT country_code, MAX(last_checked) AS last "
            "FROM job_platforms WHERE country_code = ANY($1::text[]) "
            "GROUP BY country_code",
            codes,
        )
    fresh = {
        r["country_code"]
        for r in rows
        if r["last"] is not None
        and (datetime.now(timezone.utc) - r["last"]).total_seconds()
        < fresh_within_hours * 3600
    }
    return [c for c in codes if c not in fresh]
