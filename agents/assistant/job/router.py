import logging
from typing import Optional

import boto3
from botocore.config import Config
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from assistant.job import agent as job_agent
from assistant.job import countries as job_countries
from assistant.job.application.service import generate_application
from assistant.job.db import (
    append_feedback,
    create_or_reset_application,
    fail_run,
    finish_run,
    get_application,
    get_application_by_match,
    get_application_pdf,
    get_latest_run,
    get_match,
    init_pool,
    list_matches,
    set_status,
    start_run,
)
from assistant.job.models import RunReport
from assistant.job.report import format_report
from assistant.shared.auth import require_user
from assistant.shared.settings import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["jobs"])

# Last run report per user (in-memory). Internal/legacy callers key off the seed admin.
_latest_reports: dict[str, RunReport] = {}
_seed_admin_id: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str


class FeedbackBody(BaseModel):
    feedback: str


async def _resolve_user_id(ident: dict, pool) -> str:
    """The caller's user_id, or the seed admin for internal/legacy callers.
    # MUST SCOPE BY USER"""
    if ident.get("user_id"):
        return ident["user_id"]
    global _seed_admin_id
    if _seed_admin_id is None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM users WHERE is_admin = true LIMIT 1")
        if not row:
            raise HTTPException(503, "No admin user to attribute internal job data to")
        _seed_admin_id = str(row["id"])
    return _seed_admin_id


@router.get("/countries")
async def get_countries(ident: dict = Depends(require_user)):
    """The country list for the dashboard dropdown (ISO alpha-2 code + name)."""
    return {"countries": job_countries.as_dicts()}


@router.get("/run")
async def trigger_run(
    background_tasks: BackgroundTasks,
    countries: list[str] = Query(
        default=[],
        description="ISO 3166-1 alpha-2 country codes to search, e.g. ?countries=CH&countries=DE",
    ),
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    # Per-user: matches scrape into the caller's own pool (scoped by user_id).
    # Search criteria are still the shared defaults — per-user criteria is a follow-up.
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")

    # Validate the user's country selection. At least one is required, and every
    # code must be a known ISO alpha-2 — no country is hardcoded server-side.
    codes = [c.upper() for c in countries if c and c.strip()]
    if not codes:
        raise HTTPException(422, "Select at least one country to search (GET /api/jobs/countries).")
    invalid = [c for c in codes if not job_countries.is_valid(c)]
    if invalid:
        raise HTTPException(422, f"Unknown country code(s): {', '.join(invalid)}")

    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)
    # Record the run as 'running' before we return so a poll of /report
    # immediately reflects real state — and a crash/restart mid-run leaves a
    # row that /report surfaces as 'interrupted' instead of a silent 404.
    run_id = await start_run(pool, user_id=user_id, countries=codes)
    background_tasks.add_task(
        _run_job_agent, settings, user_id, ident["token"], codes, run_id
    )
    return {
        "status": "started",
        "message": "Job hunt agent running in background. Poll GET /api/jobs/report for results.",
    }


@router.get("/matches")
async def get_matches(
    tier: Optional[str] = Query(None, description="STRONG_MATCH | GOOD_MATCH"),
    country: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)
    matches = await list_matches(pool, tier=tier, country=country, status=status, user_id=user_id)
    return {"count": len(matches), "matches": matches}


@router.post("/matches/{match_id}/status")
async def update_status(
    match_id: int,
    body: StatusUpdate,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)
    ok = await set_status(pool, match_id, body.status, user_id=user_id)
    if not ok:
        raise HTTPException(
            400,
            f"Invalid status '{body.status}' or match #{match_id} not found. "
            "Valid: new | reviewing | applied | interviewing | rejected | withdrawn | expired",
        )
    return {"id": match_id, "status": body.status}


# ── Job applications (AI "Apply" flow) ────────────────────────────────────────


def _serialize_application(app: dict) -> dict:
    """Shape an application row for the API (no pdf bytes; ISO timestamps)."""
    return {
        "id": app["id"],
        "match_id": app["match_id"],
        "status": app["status"],
        "cover_letter": app.get("cover_letter"),
        "manifest": app.get("manifest"),
        "feedback_history": app.get("feedback_history") or [],
        "error": app.get("error"),
        "iterations": app.get("iterations", 0),
        "has_pdf": app.get("has_pdf", False),
        "updated_at": app["updated_at"].isoformat() if app.get("updated_at") else None,
        "created_at": app["created_at"].isoformat() if app.get("created_at") else None,
    }


@router.post("/matches/{match_id}/application")
async def start_application(
    match_id: int,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    """Kick off AI generation of an application for this match (background)."""
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)

    match = await get_match(pool, match_id, user_id=user_id)
    if match is None:
        raise HTTPException(404, f"Job match #{match_id} not found")

    app_id = await create_or_reset_application(pool, match_id, user_id=user_id)
    background_tasks.add_task(
        generate_application,
        settings,
        token=ident["token"],
        user_id=user_id,
        match_id=match_id,
        app_id=app_id,
    )
    return {"application_id": app_id, "status": "generating"}


@router.get("/matches/{match_id}/application")
async def get_application_for_match(
    match_id: int,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)
    app = await get_application_by_match(pool, match_id, user_id=user_id)
    if app is None:
        raise HTTPException(404, "No application for this match yet")
    return _serialize_application(app)


@router.get("/applications/{app_id}")
async def get_application_status(
    app_id: int,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)
    app = await get_application(pool, app_id, user_id=user_id)
    if app is None:
        raise HTTPException(404, f"Application #{app_id} not found")
    return _serialize_application(app)


@router.get("/applications/{app_id}/pdf")
async def download_application_pdf(
    app_id: int,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)
    pdf = await get_application_pdf(pool, app_id, user_id=user_id)
    if pdf is None:
        raise HTTPException(404, "Application PDF is not ready")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="application-{app_id}.pdf"'},
    )


@router.post("/applications/{app_id}/feedback")
async def submit_application_feedback(
    app_id: int,
    body: FeedbackBody,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    """Apply the user's free-text feedback and regenerate the application."""
    feedback = (body.feedback or "").strip()
    if not feedback:
        raise HTTPException(422, "Feedback text is required")
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)

    app = await get_application(pool, app_id, user_id=user_id)
    if app is None:
        raise HTTPException(404, f"Application #{app_id} not found")

    await append_feedback(pool, app_id, feedback, user_id=user_id)
    # Re-open the row to 'generating' so polling reflects the in-progress revision.
    await create_or_reset_application(pool, app["match_id"], user_id=user_id)
    background_tasks.add_task(
        generate_application,
        settings,
        token=ident["token"],
        user_id=user_id,
        match_id=app["match_id"],
        app_id=app_id,
        feedback=feedback,
    )
    return {"application_id": app_id, "status": "generating"}


@router.post("/applications/{app_id}/apply")
async def mark_application_applied(
    app_id: int,
    settings: Settings = Depends(get_settings),
    ident: dict = Depends(require_user),
):
    """Mark the underlying match as 'applied' and return the job URL to open."""
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")
    pool = await init_pool(settings.database_url)
    user_id = await _resolve_user_id(ident, pool)

    app = await get_application(pool, app_id, user_id=user_id)
    if app is None:
        raise HTTPException(404, f"Application #{app_id} not found")
    match = await get_match(pool, app["match_id"], user_id=user_id)
    if match is None:
        raise HTTPException(404, "Job match not found")

    await set_status(pool, app["match_id"], "applied", user_id=user_id)
    return {"job_url": match.get("job_url"), "match_id": app["match_id"], "status": "applied"}


@router.get("/report")
async def get_report(settings: Settings = Depends(get_settings), ident: dict = Depends(require_user)):
    pool = await init_pool(settings.database_url) if settings.database_url else None
    user_id = await _resolve_user_id(ident, pool) if pool else (ident.get("user_id") or "")

    # Persistent run status is the source of truth for whether a run is still
    # going, finished, or died — it survives a service restart, so the frontend
    # can stop polling instead of waiting out its 30-min timeout on a 404.
    latest = await get_latest_run(pool, user_id=user_id) if pool else None
    run_status = latest["status"] if latest else "idle"

    # The DB status is authoritative. Only serve the rich in-memory report when
    # the latest run is actually finished — otherwise a stale report from a
    # previous run would make a freshly-started run look 'completed' instantly.
    report = _latest_reports.get(user_id)
    if report is not None and run_status in ("completed", "idle"):
        # Report 'completed' even if the run saved no NEW matches
        # (db_saved_this_run == 0) so the UI doesn't hang on a re-run.
        return {
            "status": "completed",
            "report": format_report(report),
            "data": report,
        }

    if latest is None:
        raise HTTPException(
            404, "No run yet — call GET /api/jobs/run to start one."
        )

    # A run finished (or died) on a different process: the rich report is gone
    # but its matches are persisted and queryable via /api/jobs/matches.
    return {
        "status": run_status,
        "error": latest.get("error"),
        "run": {
            "started_at": latest["started_at"].isoformat() if latest.get("started_at") else None,
            "finished_at": latest["finished_at"].isoformat() if latest.get("finished_at") else None,
            "strong_count": latest.get("strong_count", 0),
            "good_count": latest.get("good_count", 0),
            "saved_count": latest.get("saved_count", 0),
        },
        "report": None,
        "data": None,
    }


async def _run_job_agent(
    settings: Settings,
    user_id: str,
    token: Optional[str] = None,
    countries: Optional[list[str]] = None,
    run_id: Optional[int] = None,
) -> None:
    # Bound every Bedrock call: without a read timeout a single hung/throttled
    # request stalls the whole run indefinitely. Adaptive retries add client-side
    # rate-limiting so concurrent scoring backs off instead of erroring out.
    bedrock_client = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 4, "mode": "adaptive"},
        ),
    )
    memory_client = None

    if settings.mcp_memory_url:
        from assistant.shared.memory_client import MemoryClient

        # Forward the caller's bearer token so the run summary is saved to that
        # user's own brain. Internal/timer callers forward the INTERNAL_SECRET
        # (→ seed admin); fall back to it if no token was supplied.
        memory_client = MemoryClient(
            bedrock_client=bedrock_client,
            model_id=settings.bedrock_model_id,
            server_url=settings.mcp_memory_url,
            token=token or _get_mcp_token(settings),
        )

    try:
        report = await job_agent.run_agent(
            database_url=settings.database_url,
            bedrock_client=bedrock_client,
            model_id=settings.bedrock_model_id,
            rapidapi_key=settings.rapidapi_key,
            rapidapi_host=settings.rapidapi_host,
            memory_client=memory_client,
            delay_seconds=settings.scraper_delay_seconds,
            max_per_query=settings.scraper_max_results_per_query,
            user_id=user_id,
            countries=countries or [],
            score_concurrency=settings.job_score_concurrency,
        )
        _latest_reports[user_id] = report
        if run_id is not None and settings.database_url:
            pool = await init_pool(settings.database_url)
            await finish_run(
                pool, run_id,
                strong=len(report.strong_matches),
                good=len(report.good_matches),
                saved=report.db_saved_this_run,
            )
    except Exception as exc:
        # Never fail silently: record the failure on the run row so /report can
        # tell the user the run died (and why) instead of polling forever.
        logger.exception("Job hunt agent run failed")
        if run_id is not None and settings.database_url:
            try:
                pool = await init_pool(settings.database_url)
                await fail_run(pool, run_id, f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception("Could not record job run failure")


def _get_mcp_token(settings: Settings) -> Optional[str]:
    # Same-host auth to the memory API uses the shared INTERNAL_SECRET, which
    # Service A resolves to the seed admin. Stable — no OAuth token to refresh.
    return settings.internal_secret or None
