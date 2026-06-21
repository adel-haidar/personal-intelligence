"""Fallback strategy for when discovery can't validate platforms via RapidAPI.

When the orchestrator finds that NO country could be validated (RapidAPI rejected
or rate-limited the key), it calls `resolve`. Rather than leave the dropdown
empty, we seed each country with LLM-proposed boards marked `available=False` +
`needs_key=True` — visible but flagged — and signal that human input is needed.
The GET /api/jobs/platforms/setup-guide endpoint renders the step-by-step page
that walks the user through generating a working key.
"""

import asyncio
import logging

import asyncpg

from assistant.job.platforms import catalog
from assistant.job.platforms.discovery import _build_platforms, _propose_platforms

logger = logging.getLogger(__name__)


async def resolve(
    *,
    pool: asyncpg.Pool,
    bedrock_client,
    model_id: str,
    countries: list[str],
    reason: str,
) -> tuple[int, bool]:
    """Seed LLM-only platforms (no live validation possible) for each country.

    Returns (rows_written, needs_key). `needs_key` is always True here — it's the
    signal the API surfaces so the dashboard can link to the setup guide.
    """
    loop = asyncio.get_event_loop()
    written = 0
    for code in countries:
        proposed = await loop.run_in_executor(
            None, _propose_platforms, bedrock_client, model_id, code
        )
        if not proposed:
            continue
        # validated=False keeps them on trust; then mark them as needing a key so
        # the UI flags them and points at the setup guide.
        platforms = _build_platforms(code, proposed, [], validated=False)
        for p in platforms:
            p.available = False
            p.needs_key = True
        written += await catalog.upsert_platforms(pool, platforms)

    logger.info(
        "Fallback seeded %d platform rows across %d countries (reason: %s)",
        written, len(countries), reason,
    )
    return written, True
