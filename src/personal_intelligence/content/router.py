import uuid
import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Header
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from personal_intelligence.auth.oauth import validate_token
from personal_intelligence.content.creators import list_creators
from personal_intelligence.database import _connect
from personal_intelligence.content.jobs.topic_job import run_topic_intelligence_job

router = APIRouter(prefix="/api/content")


async def _require_auth(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    token = auth[7:]
    client_id = validate_token(token)
    if not client_id:
        raise HTTPException(status_code=401, detail="invalid token")
    return client_id


def _serialize_row(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


class InteractionEvent(BaseModel):
    content_id: str
    content_type: Literal["post", "video"]
    action: Literal["like", "dislike", "skip", "watch_complete", "watch_partial", "view"]
    watch_pct: Optional[float] = None


@router.get("/creators")
async def get_creators(client_id: str = Depends(_require_auth)):
    return list_creators(active_only=True)


@router.get("/posts")
async def get_posts(
    page: int = 1,
    page_size: int = 20,
    creator_id: Optional[str] = None,
    client_id: str = Depends(_require_auth),
):
    offset = (page - 1) * page_size
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if creator_id:
        cur.execute("SELECT COUNT(*) FROM content_posts WHERE creator_id = %s", (creator_id,))
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT p.*, c.name AS creator_name, c.avatar_url AS creator_avatar
               FROM content_posts p
               JOIN content_creators c ON c.id = p.creator_id
               WHERE p.creator_id = %s
               ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
            (creator_id, page_size, offset),
        )
    else:
        cur.execute("SELECT COUNT(*) FROM content_posts")
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT p.*, c.name AS creator_name, c.avatar_url AS creator_avatar
               FROM content_posts p
               JOIN content_creators c ON c.id = p.creator_id
               ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
            (page_size, offset),
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
    client_id: str = Depends(_require_auth),
):
    offset = (page - 1) * page_size
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if status:
        cur.execute("SELECT COUNT(*) FROM content_videos WHERE status = %s", (status,))
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT v.*, c.name AS creator_name, c.avatar_url AS creator_avatar
               FROM content_videos v
               JOIN content_creators c ON c.id = v.creator_id
               WHERE v.status = %s
               ORDER BY v.created_at DESC LIMIT %s OFFSET %s""",
            (status, page_size, offset),
        )
    else:
        cur.execute("SELECT COUNT(*) FROM content_videos")
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT v.*, c.name AS creator_name, c.avatar_url AS creator_avatar
               FROM content_videos v
               JOIN content_creators c ON c.id = v.creator_id
               ORDER BY v.created_at DESC LIMIT %s OFFSET %s""",
            (page_size, offset),
        )
    rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": rows, "total": total, "page": page, "pages": pages}


@router.post("/interactions", status_code=201)
async def log_interaction(
    body: InteractionEvent,
    client_id: str = Depends(_require_auth),
):
    if body.watch_pct is not None and not (0.0 <= body.watch_pct <= 1.0):
        raise HTTPException(status_code=422, detail="watch_pct must be between 0.0 and 1.0")
    interaction_id = str(uuid.uuid4())
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO content_interactions (id, content_id, content_type, action, watch_pct)
           VALUES (%s, %s, %s, %s, %s)""",
        (interaction_id, body.content_id, body.content_type, body.action, body.watch_pct),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"id": interaction_id, "ok": True}


@router.get("/topics")
async def get_topics(
    page: int = 1,
    page_size: int = 50,
    client_id: str = Depends(_require_auth),
):
    offset = (page - 1) * page_size
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT COUNT(*) FROM content_topics")
    total = cur.fetchone()["count"]
    cur.execute(
        "SELECT * FROM content_topics ORDER BY weight DESC LIMIT %s OFFSET %s",
        (page_size, offset),
    )
    rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": rows, "total": total, "page": page, "pages": pages}


@router.post("/jobs/topics/run", status_code=202)
async def run_topic_intelligence_job_endpoint(
    background_tasks: BackgroundTasks,
    x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret"),
):
    expected_secret = os.getenv("INTERNAL_SECRET")
    if not expected_secret:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_SECRET env var is not configured on the server"
        )
    if x_internal_secret != expected_secret:
        raise HTTPException(
            status_code=401,
            detail="Invalid internal secret"
        )
    
    background_tasks.add_task(run_topic_intelligence_job)
    return {"status": "enqueued", "job": "topic_intelligence"}
