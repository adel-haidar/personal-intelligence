import json
import logging
from datetime import date, timedelta
from urllib.parse import urlparse

import asyncpg
import httpx

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

    # Step 1 — Resolve the user's weight goal from their brain (must come before
    # compute so goal-relative fields are populated correctly). None = no goal set.
    weight_goal_kg: float | None = None
    medical_records: list[tuple[str, str]] = []
    user_profile = ""
    memory_client = None
    if mcp_url and mcp_token:
        from assistant.shared.memory_client import MemoryClient
        from assistant.shared.user_profile import build_user_profile

        memory_client = MemoryClient(
            bedrock_client=bedrock_client,
            model_id=model_id,
            server_url=mcp_url,
            token=mcp_token,
        )
        try:
            weight_goal_kg = await memory_client.fetch_weight_goal()
            if weight_goal_kg is not None:
                logger.info("Weight goal resolved from brain: %.1f kg", weight_goal_kg)
            else:
                logger.info("No weight goal set in brain — goal-relative fields will be None")
        except Exception:
            logger.warning("Failed to fetch weight goal from brain", exc_info=True)

        try:
            medical_records = await fetch_medical_records(mcp_url, mcp_token)
        except Exception:
            logger.warning("Failed to fetch medical records from MCP memory", exc_info=True)

        # Build the per-user "ABOUT THE USER" block from the CALLER's own brain so
        # the coach reasons about this user (weight/goal/training), not the owner.
        try:
            user_profile = await build_user_profile(memory_client, domain="health")
        except Exception:
            logger.warning("Failed to build user profile for health analysis", exc_info=True)

    # Step 2 — Compute today's summary (pure Python, no LLM)
    summary = await compute_daily_summary(
        pool, target_date, user_id=user_id, weight_goal_kg=weight_goal_kg
    )

    # Step 3 — Pull last 14 days for flag detection (pure Python, no LLM)
    history = []
    for i in range(1, 15):
        past = target_date - timedelta(days=i)
        history.append(await compute_daily_summary(
            pool, past, user_id=user_id, weight_goal_kg=weight_goal_kg
        ))

    flags = await detect_flags(pool, summary, history, user_id=user_id)

    # Step 4 — Per-source data availability: did the scale / watch report today,
    # and if not, when is new data expected? (pure Python, no LLM)
    availability = await compute_source_availability(pool, target_date, user_id=user_id)

    # Step 5 — Generate analysis (single LLM call, temp=0, tool_use):
    # coach_insight + basic analysis + mandatory reasoning
    llm = generate_health_analysis(
        summary, flags, availability, medical_records, bedrock_client, model_id,
        user_profile=user_profile,
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


def _api_base_url(mcp_url: str) -> str:
    """'https://host/mcp/mcp' → 'https://host'. The daily summary is persisted via
    the REST memory API, NOT the MCP protocol endpoint. The MCP `/mcp` endpoint
    is OAuth-only (claude.ai), so forwarding the platform JWT to it 401s and the
    save silently failed. The REST `/api/memory/*` routes accept the platform JWT
    via RequestContext (same path fetch_medical_records already uses)."""
    parsed = urlparse(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def _find_existing_summary_id(
    client: httpx.AsyncClient, base_url: str, title: str
) -> str | None:
    """memory_id of an existing memory with this EXACT title, if any — so daily
    re-runs UPDATE the same summary instead of piling up duplicates."""
    resp = await client.get(
        f"{base_url}/api/memory",
        params={"q": title, "page": "1", "page_size": "100"},
    )
    resp.raise_for_status()
    for item in resp.json().get("items", []):
        if (item.get("title") or "").strip() == title:
            # The list endpoint serializes the id as "id"; search uses "memory_id".
            return item.get("id") or item.get("memory_id")
    return None


async def _save_to_mcp_memory(
    result: HealthInsightResponse,
    mcp_url: str,
    token: str,
) -> None:
    """Persist the daily health summary via the REST memory API, upserting by title."""
    base_url = _api_base_url(mcp_url)
    title = f"Health summary {result.date.isoformat()}"
    content = result.model_dump_json()
    tags = ["health", "daily", result.date.isoformat()] + result.flags
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"title": title, "content": content, "tags": tags}

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        existing_id = await _find_existing_summary_id(client, base_url, title)
        if existing_id:
            resp = await client.patch(f"{base_url}/api/memory/{existing_id}", json=payload)
        else:
            resp = await client.post(f"{base_url}/api/memory/text", json=payload)
        resp.raise_for_status()
    logger.info(
        "Health summary %s saved to memory (%s)",
        result.date.isoformat(),
        "updated" if existing_id else "created",
    )


async def fetch_from_mcp_memory(
    target_date: date,
    mcp_url: str,
    token: str,
) -> HealthInsightResponse | None:
    """Retrieve a previously saved daily health summary via the REST memory API."""
    base_url = _api_base_url(mcp_url)
    title = f"Health summary {target_date.isoformat()}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            resp = await client.get(
                f"{base_url}/api/memory",
                params={"q": title, "page": "1", "page_size": "100"},
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        for item in items:
            if (item.get("title") or "").strip() != title:
                continue
            content = item.get("content")
            if not content:
                continue
            try:
                data = json.loads(content)
                parsed = HealthInsightResponse.model_validate(data)
                if str(parsed.date) == target_date.isoformat():
                    return parsed
            except Exception:
                continue
    except Exception:
        logger.warning("Failed to fetch health summary from memory", exc_info=True)
    return None
