import io
import logging
import os
import tempfile
import zipfile
from datetime import date, datetime

import boto3
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from functools import lru_cache

from assistant.health.compute import compute_daily_summary
from assistant.health.db import bulk_insert, fetch_trends, get_pool, init_pool
from assistant.health.ingest import parse_apple_health_export
from assistant.health.models import (
    DailyHealthSummary,
    HealthInsightResponse,
    ManualEntryRequest,
    HealthMetric,
    SOURCE,
)
from assistant.health.workflow import fetch_from_mcp_memory, run_daily_health_workflow
from assistant.shared.auth import require_user
from assistant.shared.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

TREND_METRICS = ["weight_kg", "resting_hr", "sleep_duration_min", "steps",
                 "hrv_ms", "active_energy_kcal", "body_fat_percent"]

_seed_admin_id: str | None = None


async def _resolve_user_id(ident: dict, pool) -> str:
    """The effective user_id to scope health data by.  # MUST SCOPE BY USER

    Platform JWT callers → their own user_id. Internal (cron via INTERNAL_SECRET)
    and legacy OAuth callers carry no user_id, so they attribute to the seed admin
    — preserving the owner's existing daily pipeline."""
    if ident.get("user_id"):
        return ident["user_id"]
    global _seed_admin_id
    if _seed_admin_id is None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM users WHERE is_admin = true LIMIT 1")
        if not row:
            raise HTTPException(503, "No admin user to attribute internal health data to")
        _seed_admin_id = str(row["id"])
    return _seed_admin_id


@lru_cache
def _bedrock(region: str):
    return boto3.client("bedrock-runtime", region_name=region)


async def _pool():
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL not configured")
    return await init_pool(settings.database_url)


# ── Import ────────────────────────────────────────────────────────────────────

@router.post("/health/import/apple-health")
async def import_apple_health(
    file: UploadFile = File(...),
    ident: dict = Depends(require_user),
):
    """Accept the Apple Health export — either the raw export.xml OR the
    'Export All Health Data' .zip (which contains apple_health_export/export.xml).
    Streams to /tmp, parses, bulk-inserts new rows for the calling user."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)

    # Stream to temp file to avoid loading 100MB+ into memory
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp_path = tmp.name
        chunk_size = 64 * 1024
        while chunk := await file.read(chunk_size):
            tmp.write(chunk)

    try:
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        os.unlink(tmp_path)

    # The .zip archive starts with the ZIP magic bytes "PK". Extract export.xml
    # from it so users can upload the file Apple gives them without unzipping.
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = [n for n in zf.namelist() if n.endswith("export.xml")]
                if not names:
                    raise HTTPException(
                        400, "That .zip doesn't contain an Apple Health export.xml."
                    )
                xml_bytes = zf.read(names[0])
        except zipfile.BadZipFile:
            raise HTTPException(400, "Could not read that .zip file.")
    else:
        xml_bytes = data

    metrics = parse_apple_health_export(xml_bytes)
    if not metrics:
        return {"inserted": 0, "date_range": [None, None]}

    inserted = await bulk_insert(pool, metrics, user_id=user_id)

    dates = [m.recorded_at.date().isoformat() for m in metrics]
    date_range = [min(dates), max(dates)]

    return {"inserted": inserted, "date_range": date_range}


# ── Manual entry ──────────────────────────────────────────────────────────────

@router.post("/health/manual-entry")
async def manual_entry(
    body: ManualEntryRequest,
    ident: dict = Depends(require_user),
):
    """Insert a single metric with source='manual'. For days when the export is stale."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    from assistant.health.db import insert_one

    metric = HealthMetric(
        recorded_at=body.recorded_at,
        metric_type=body.metric_type,
        value=body.value,
        unit=body.unit,
        source="manual",
    )
    saved = await insert_one(pool, metric, user_id=user_id)
    return {"saved": saved}


# ── Workflow trigger ──────────────────────────────────────────────────────────

@router.post("/health/run-daily/{target_date}", response_model=HealthInsightResponse)
async def run_daily(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Trigger the full workflow for a specific date (used by cron / manual trigger).
    Scopes metric reads to the caller and forwards the caller's token so the summary
    saves to the caller's brain (cron's INTERNAL_SECRET → seed admin, unchanged)."""
    settings = get_settings()
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    bedrock_client = _bedrock(settings.aws_region)

    mcp_url = settings.mcp_memory_url
    # Forward the caller's bearer so MCP memory scopes to the right tenant.
    mcp_token = ident["token"] if mcp_url else None

    return await run_daily_health_workflow(
        target_date=target_date,
        pool=pool,
        bedrock_client=bedrock_client,
        model_id=settings.bedrock_model_id,
        mcp_url=mcp_url,
        mcp_token=mcp_token,
        user_id=user_id,
    )


# ── Fetch previous run ────────────────────────────────────────────────────────

@router.get("/health/daily/{target_date}", response_model=HealthInsightResponse)
async def get_daily(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Return a previously computed daily summary from the caller's MCP memory (no LLM re-run)."""
    settings = get_settings()
    if not settings.mcp_memory_url:
        raise HTTPException(503, "MCP_MEMORY_URL not configured")

    # Forward the caller's token → MCP memory scopes the lookup to their tenant.
    result = await fetch_from_mcp_memory(target_date, settings.mcp_memory_url, ident["token"])
    if not result:
        # Do NOT raise 404 here: CloudFront rewrites 403/404 responses to the
        # SPA's index.html (status 200), so the frontend would receive HTML
        # instead of this error. Return a structured "not run" payload instead.
        return HealthInsightResponse(
            date=target_date,
            status="not_run",
            summary=DailyHealthSummary(date=target_date),
            flags=[],
            coach_insight="",
            reasoning=(
                f"No stored health summary for {target_date.isoformat()} — "
                "the daily workflow has not run for this date yet."
            ),
        )
    return result


# ── Trends ───────────────────────────────────────────────────────────────────

@router.get("/health/trends")
async def get_trends(
    days: int = Query(default=30, ge=1, le=365),
    ident: dict = Depends(require_user),
):
    """Return daily time series for charting: weight, resting_hr, sleep, steps, etc."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    series = await fetch_trends(pool, TREND_METRICS, days, user_id=user_id)
    return {"days": days, "series": series}


# ── Summary (no LLM) ─────────────────────────────────────────────────────────

@router.get("/health/summary/{target_date}", response_model=DailyHealthSummary)
async def get_summary(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Compute and return a daily summary on-demand (no LLM call, no insight)."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    return await compute_daily_summary(pool, target_date, user_id=user_id)
