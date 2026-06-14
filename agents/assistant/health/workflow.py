import json
import logging
from datetime import date, timedelta

import asyncpg
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from assistant.health.compute import (
    compute_daily_summary,
    compute_source_availability,
    detect_flags,
)
from assistant.health.insight import generate_health_analysis
from assistant.health.models import HealthInsightResponse
from assistant.health.records import fetch_medical_records

logger = logging.getLogger(__name__)


async def run_daily_health_workflow(
    target_date: date,
    pool: asyncpg.Pool,
    bedrock_client,
    model_id: str,
    mcp_url: str | None = None,
    mcp_token: str | None = None,
    *,
    user_id: str,
) -> HealthInsightResponse:
    """Fixed-order, non-agentic workflow. Steps run sequentially every time.
    # MUST SCOPE BY USER — all metric reads + the memory save are for `user_id`."""

    # Step 1 — Compute today's summary (pure Python, no LLM)
    summary = await compute_daily_summary(pool, target_date, user_id=user_id)

    # Step 2 — Pull last 14 days for flag detection (pure Python, no LLM)
    history = []
    for i in range(1, 15):
        past = target_date - timedelta(days=i)
        history.append(await compute_daily_summary(pool, past, user_id=user_id))

    flags = await detect_flags(pool, summary, history, user_id=user_id)

    # Step 3 — Per-source data availability: did the scale / watch report today,
    # and if not, when is new data expected? (pure Python, no LLM)
    availability = await compute_source_availability(pool, target_date, user_id=user_id)

    # Step 4 — Fetch medical records from MCP memory (titles are reported back
    # to the caller as the list of documents the analysis is based on)
    medical_records: list[tuple[str, str]] = []
    if mcp_url and mcp_token:
        try:
            medical_records = await fetch_medical_records(mcp_url, mcp_token)
        except Exception:
            logger.warning("Failed to fetch medical records from MCP memory", exc_info=True)

    # Step 5 — Generate analysis (single LLM call, temp=0, tool_use):
    # coach_insight + basic analysis + mandatory reasoning
    llm = generate_health_analysis(
        summary, flags, availability, medical_records, bedrock_client, model_id
    )

    # Step 6 — Assemble response
    result = HealthInsightResponse(
        date=target_date,
        summary=summary,
        flags=flags,
        coach_insight=llm["coach_insight"],
        analysis=llm["analysis"],
        reasoning=llm["reasoning"],
        documents=[title for title, _ in medical_records],
        data_availability=availability,
    )

    # Step 7 — Persist to MCP memory
    if mcp_url and mcp_token:
        try:
            await _save_to_mcp_memory(result, mcp_url, mcp_token)
        except Exception:
            logger.warning("Failed to save health summary to MCP memory", exc_info=True)

    return result


async def _save_to_mcp_memory(
    result: HealthInsightResponse,
    mcp_url: str,
    token: str,
) -> None:
    """Persist the daily health summary to MCP memory with searchable tags."""
    title = f"Health summary {result.date.isoformat()}"
    content = result.model_dump_json()
    tags = ["health", "daily", result.date.isoformat()] + result.flags

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers) as http_client:
        async with streamable_http_client(
            url=mcp_url, http_client=http_client
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool(
                    "save",
                    {"title": title, "content": content, "tags": tags},
                )
    logger.info("Health summary %s saved to MCP memory", result.date.isoformat())


async def fetch_from_mcp_memory(
    target_date: date,
    mcp_url: str,
    token: str,
) -> HealthInsightResponse | None:
    """Retrieve a previously saved daily health summary from MCP memory."""
    query = f"Health summary {target_date.isoformat()}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(
                url=mcp_url, http_client=http_client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("search", {"query": query})
                    if result.isError or not result.content:
                        return None
                    for item in result.content:
                        if not hasattr(item, "text") or not item.text:
                            continue
                        try:
                            data = json.loads(item.text)
                            parsed = HealthInsightResponse.model_validate(data)
                            if str(parsed.date) == target_date.isoformat():
                                return parsed
                        except Exception:
                            continue
    except Exception:
        logger.warning("Failed to fetch health summary from MCP memory", exc_info=True)
    return None
