import uuid
import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from private_internet.content.creators import list_creators
from private_internet.core.jobs import run_for_all_users
from private_internet.core.request_context import RequestContext, get_request_context
from private_internet.database import _connect
from private_internet.content.jobs.topic_job import run_topic_intelligence_job
from private_internet.content.jobs.post_job import generate_posts_batch
from private_internet.content.jobs.video_job import generate_videos_batch

router = APIRouter(prefix="/api/content")

# All read/write endpoints are scoped to the authenticated user.
# MUST SCOPE BY USER  (creators are shared platform personas — no scoping)


async def _require_internal_secret(
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
) -> None:
    expected_secret = os.getenv("INTERNAL_SECRET")
    if not expected_secret:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_SECRET env var is not configured on the server",
        )
    if x_internal_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


def _serialize_row(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif k == "user_id":
            result[k] = str(v)
        else:
            result[k] = v
    return result


class InteractionEvent(BaseModel):
    content_id: str
    content_type: Literal["post", "video"]
    action: Literal["like", "dislike", "skip", "watch_complete", "watch_partial", "view"]
    watch_pct: Optional[float] = None


@router.get("/creators")
async def get_creators(ctx: RequestContext = Depends(get_request_context)):
    return list_creators(active_only=True)


# Sort modes for the PULSE feed (Phase 5). Values are vetted ORDER BY clauses —
# the user-supplied `sort` key never reaches the SQL directly.
_POST_SORTS = {
    "latest": "p.created_at DESC",
    "top": "p.score DESC, p.created_at DESC",
    "unrated": "p.total_interactions ASC, p.created_at DESC",
}


@router.get("/posts")
async def get_posts(
    page: int = 1,
    page_size: int = 20,
    creator_id: Optional[str] = None,
    sort: str = "latest",
    ctx: RequestContext = Depends(get_request_context),
):
    order_by = _POST_SORTS.get(sort)
    if order_by is None:
        raise HTTPException(
            status_code=422, detail=f"sort must be one of {sorted(_POST_SORTS)}"
        )
    offset = (page - 1) * page_size
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    select = """SELECT p.*, c.name AS creator_name, c.avatar_url AS creator_avatar,
                       c.slug AS creator_slug, c.score AS creator_score, c.bio AS creator_bio
                FROM content_posts p
                JOIN content_creators c ON c.id = p.creator_id"""
    if creator_id:
        cur.execute(
            "SELECT COUNT(*) FROM content_posts WHERE user_id = %s AND creator_id = %s",
            (ctx.user_id, creator_id),
        )
        total = cur.fetchone()["count"]
        cur.execute(
            f"{select} WHERE p.user_id = %s AND p.creator_id = %s "
            f"ORDER BY {order_by} LIMIT %s OFFSET %s",
            (ctx.user_id, creator_id, page_size, offset),
        )
    else:
        cur.execute("SELECT COUNT(*) FROM content_posts WHERE user_id = %s", (ctx.user_id,))
        total = cur.fetchone()["count"]
        cur.execute(
            f"{select} WHERE p.user_id = %s ORDER BY {order_by} LIMIT %s OFFSET %s",
            (ctx.user_id, page_size, offset),
        )
    rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": rows, "total": total, "page": page, "pages": pages}


@router.get("/videos")
async def get_videos(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    ctx: RequestContext = Depends(get_request_context),
):
    offset = (page - 1) * page_size
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if status:
        cur.execute(
            "SELECT COUNT(*) FROM content_videos WHERE user_id = %s AND status = %s",
            (ctx.user_id, status),
        )
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT v.*, c.name AS creator_name, c.avatar_url AS creator_avatar
               FROM content_videos v
               JOIN content_creators c ON c.id = v.creator_id
               WHERE v.user_id = %s AND v.status = %s
               ORDER BY v.created_at DESC LIMIT %s OFFSET %s""",
            (ctx.user_id, status, page_size, offset),
        )
    else:
        cur.execute("SELECT COUNT(*) FROM content_videos WHERE user_id = %s", (ctx.user_id,))
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT v.*, c.name AS creator_name, c.avatar_url AS creator_avatar
               FROM content_videos v
               JOIN content_creators c ON c.id = v.creator_id
               WHERE v.user_id = %s
               ORDER BY v.created_at DESC LIMIT %s OFFSET %s""",
            (ctx.user_id, page_size, offset),
        )
    rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": rows, "total": total, "page": page, "pages": pages}


@router.post("/interactions", status_code=201)
async def log_interaction(
    body: InteractionEvent,
    ctx: RequestContext = Depends(get_request_context),
):
    if body.watch_pct is not None and not (0.0 <= body.watch_pct <= 1.0):
        raise HTTPException(status_code=422, detail="watch_pct must be between 0.0 and 1.0")
    interaction_id = str(uuid.uuid4())
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO content_interactions (id, content_id, content_type, action, watch_pct, user_id)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (interaction_id, body.content_id, body.content_type, body.action, body.watch_pct,
         ctx.user_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"id": interaction_id, "ok": True}


@router.get("/topics")
async def get_topics(
    page: int = 1,
    page_size: int = 50,
    ctx: RequestContext = Depends(get_request_context),
):
    offset = (page - 1) * page_size
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT COUNT(*) FROM content_topics WHERE user_id = %s", (ctx.user_id,))
    total = cur.fetchone()["count"]
    cur.execute(
        "SELECT * FROM content_topics WHERE user_id = %s ORDER BY weight DESC LIMIT %s OFFSET %s",
        (ctx.user_id, page_size, offset),
    )
    rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": rows, "total": total, "page": page, "pages": pages}


# ── Job triggers ────────────────────────────────────────────────────────────
# Internal-secret endpoints (EventBridge / cron) iterate over ALL onboarded
# users. Authenticated users can also trigger their own pipelines (used by
# the dashboard's "generate now" buttons).


@router.post("/jobs/topics/run", status_code=202)
async def run_topic_intelligence_job_endpoint(
    background_tasks: BackgroundTasks,
    _: None = Depends(_require_internal_secret),
):
    background_tasks.add_task(run_for_all_users, run_topic_intelligence_job)
    return {"status": "enqueued", "job": "topic_intelligence", "scope": "all_users"}


class PostsJobRequest(BaseModel):
    count: int = 3


@router.post("/jobs/posts/run", status_code=202)
async def run_post_generation_job_endpoint(
    background_tasks: BackgroundTasks,
    body: Optional[PostsJobRequest] = None,
    _: None = Depends(_require_internal_secret),
):
    count = body.count if body else 3
    if not (1 <= count <= 10):
        raise HTTPException(status_code=422, detail="count must be between 1 and 10")
    background_tasks.add_task(run_for_all_users, generate_posts_batch, count=count)
    return {"status": "enqueued", "job": "post_generation", "count": count, "scope": "all_users"}


class VideosJobRequest(BaseModel):
    count: int = 1
    topic_id: Optional[str] = None


@router.post("/jobs/videos/run", status_code=202)
async def run_video_generation_job_endpoint(
    background_tasks: BackgroundTasks,
    body: Optional[VideosJobRequest] = None,
    _: None = Depends(_require_internal_secret),
):
    count = body.count if body else 1
    topic_id = body.topic_id if body else None
    if not (1 <= count <= 5):
        raise HTTPException(status_code=422, detail="count must be between 1 and 5")
    background_tasks.add_task(
        run_for_all_users, generate_videos_batch, count=count, topic_id=topic_id
    )
    return {"status": "enqueued", "job": "video_generation", "count": count,
            "topic_id": topic_id, "scope": "all_users"}


@router.post("/jobs/mine/run", status_code=202)
async def run_my_pipelines_endpoint(
    background_tasks: BackgroundTasks,
    ctx: RequestContext = Depends(get_request_context),
):
    """Generate content for the requesting user only — the dashboard's
    'TRIGGER CONTENT GENERATION' button."""

    async def _run_mine():
        await run_topic_intelligence_job(user_id=ctx.user_id)
        await generate_posts_batch(count=3, user_id=ctx.user_id)

    background_tasks.add_task(_run_mine)
    return {"status": "enqueued", "job": "user_pipeline", "scope": "self"}
