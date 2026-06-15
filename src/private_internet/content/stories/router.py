"""STORIES API router — /api/stories endpoints.

All endpoints are scoped to the authenticated user via RequestContext.
CloudFront URLs are stored directly in the DB (set during generation) and
returned as-is — no presigned URLs, matching the repo's AssetStore pattern.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from private_internet.content.stories import db as stories_db
from private_internet.content.stories.models import (
    CategoryOut,
    ContinueWatchingItem,
    EpisodeSummary,
    FilmDetail,
    FilmSummary,
    GenerateFilmIn,
    LibraryOut,
    LikeIn,
    LikeOut,
    SearchOut,
    SeriesDetail,
    SeriesSummary,
    StatusCountsOut,
    WatchProgressIn,
    WatchProgressOut,
)
from private_internet.content.router import _require_internal_secret
from private_internet.core.jobs import run_for_all_users
from private_internet.core.request_context import RequestContext, get_request_context
from private_internet.database import _connect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stories")


# ── Serialisation helper ──────────────────────────────────────────────────────

def _ser(row: dict) -> dict:
    """Normalise a DB row: stringify UUIDs, convert datetime to iso."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = str(v) if hasattr(v, "hex") else v  # UUID → str
    return out


# ── Library ───────────────────────────────────────────────────────────────────

@router.get("/", response_model=LibraryOut)
async def get_library(ctx: RequestContext = Depends(get_request_context)):
    """Return films, series, categories, and continue-watching for the user."""
    conn = _connect()
    try:
        films_raw = stories_db.list_films(conn, user_id=ctx.user_id, limit=20)
        series_raw = stories_db.list_series(conn, user_id=ctx.user_id, limit=20)
        categories_raw = stories_db.list_categories(conn, user_id=ctx.user_id)
        progress_raw = stories_db.continue_watching(conn, user_id=ctx.user_id, limit=10)

        # Enrich continue_watching items with titles + thumbnails
        cw_items = []
        for p in progress_raw:
            title, thumb = None, None
            ctype = p.get("content_type")
            cid = str(p.get("content_id", ""))
            if ctype == "film":
                film = stories_db.get_film(conn, cid, user_id=ctx.user_id)
                if film:
                    title, thumb = film.get("title"), film.get("thumbnail_url")
            # episode enrichment — look up via a separate query
            elif ctype == "episode":
                cur = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cur.execute(
                        "SELECT title, thumbnail_url FROM stories_episodes WHERE id = %s AND user_id = %s",
                        (cid, ctx.user_id),
                    )
                    ep = cur.fetchone()
                    if ep:
                        title, thumb = ep["title"], ep["thumbnail_url"]
                finally:
                    cur.close()

            cw_items.append(
                ContinueWatchingItem(
                    content_type=p["content_type"],
                    content_id=p["content_id"],
                    title=title,
                    thumbnail_url=thumb,
                    position_seconds=p["position_seconds"],
                    duration_seconds=p.get("duration_seconds"),
                    completed=p["completed"],
                    last_watched_at=p["last_watched_at"],
                )
            )

        return LibraryOut(
            films=[FilmSummary(**_ser(f)) for f in films_raw],
            series=[SeriesSummary(**_ser(s)) for s in series_raw],
            categories=[CategoryOut(**c) for c in categories_raw],
            continue_watching=cw_items,
        )
    finally:
        conn.close()


# ── Films ─────────────────────────────────────────────────────────────────────

@router.get("/films/{film_id}", response_model=FilmDetail)
async def get_film(film_id: UUID, ctx: RequestContext = Depends(get_request_context)):
    """Film detail with CloudFront video/poster/thumbnail URLs, watch progress, and related films."""
    conn = _connect()
    try:
        film = stories_db.get_film(conn, str(film_id), user_id=ctx.user_id)
        if not film:
            raise HTTPException(status_code=404, detail="Film not found")

        progress = stories_db.get_watch_progress(
            conn,
            user_id=ctx.user_id,
            content_type="film",
            content_id=str(film_id),
        )
        related_raw = stories_db.get_related_films(
            conn, str(film_id), film.get("category"), user_id=ctx.user_id, limit=6
        )
        liked = stories_db.is_liked(
            conn, user_id=ctx.user_id, content_type="film", content_id=str(film_id)
        )

        wp_out = (
            WatchProgressOut(**_ser(progress)) if progress else None
        )
        return FilmDetail(
            **_ser(film),
            watch_progress=wp_out,
            related=[FilmSummary(**_ser(r)) for r in related_raw],
            liked=liked,
        )
    finally:
        conn.close()


@router.post("/films/generate", status_code=202)
async def generate_film_endpoint(
    body: GenerateFilmIn,
    background_tasks: BackgroundTasks,
    ctx: RequestContext = Depends(get_request_context),
):
    """Trigger STORIES film generation in the background. Returns immediately with the film_id."""
    from private_internet.content.stories.generator import generate_film

    # Insert the reservation row synchronously so the caller has an id to poll.
    conn = _connect()
    try:
        film_id = stories_db.insert_film(
            conn,
            user_id=ctx.user_id,
            title=body.title,
            premise=body.premise,
            category=body.category,
        )
    finally:
        conn.close()

    async def _run():
        from private_internet.content.stories.db import update_film_status
        from private_internet.database import _connect as connect2
        try:
            # We already inserted the row above; call the internals directly
            # (generate_film would insert a second row, so we use the lower-level
            # approach: run generate_video, then update the existing row).
            from private_internet.content.jobs.video_job import generate_video
            from private_internet.content.asset_store import AssetStore
            from private_internet.content.stories.generator import _generate_poster
            from psycopg2.extras import RealDictCursor

            video_id = await generate_video(body.topic_id, user_id=ctx.user_id)

            conn2 = connect2()
            try:
                cur = conn2.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT video_url, thumbnail_url, duration_seconds FROM content_videos WHERE id = %s AND user_id = %s",
                    (video_id, ctx.user_id),
                )
                vr = cur.fetchone()
                cur.close()

                poster_bytes = await _generate_poster(body.title, body.premise)
                asset_store = AssetStore()
                poster_url = asset_store._upload(f"stories/{film_id}/poster.png", poster_bytes, "image/png")

                update_film_status(
                    conn2,
                    film_id,
                    "ready",
                    user_id=ctx.user_id,
                    signal_video_id=video_id,
                    video_url=vr["video_url"] if vr else None,
                    thumbnail_url=vr["thumbnail_url"] if vr else None,
                    poster_url=poster_url,
                    duration_seconds=vr["duration_seconds"] if vr else None,
                )
            finally:
                conn2.close()
        except Exception as exc:
            logger.error("[user:%s] Background film generation failed: %s", ctx.user_id[:8], exc, exc_info=True)
            conn3 = _connect()
            try:
                update_film_status(conn3, film_id, "failed", user_id=ctx.user_id, error_message=str(exc)[:512])
            finally:
                conn3.close()

    background_tasks.add_task(_run)
    return {"film_id": film_id, "status": "generating"}


@router.post("/jobs/run", status_code=202)
async def run_film_generation_job_endpoint(
    background_tasks: BackgroundTasks,
    count: int = 1,
    _: None = Depends(_require_internal_secret),
):
    """Internal-secret cron endpoint (systemd timer / EventBridge): generate
    `count` STORIES films for ALL onboarded users. Titles/premises are
    auto-derived from each user's topics — no client input required."""
    if not (1 <= count <= 3):
        raise HTTPException(status_code=422, detail="count must be between 1 and 3")
    from private_internet.content.stories.generator import generate_films_batch

    background_tasks.add_task(run_for_all_users, generate_films_batch, count=count)
    return {"status": "enqueued", "job": "film_generation", "count": count,
            "scope": "all_users"}


# ── Series ────────────────────────────────────────────────────────────────────

@router.get("/series/{series_id}", response_model=SeriesDetail)
async def get_series(series_id: UUID, ctx: RequestContext = Depends(get_request_context)):
    conn = _connect()
    try:
        series = stories_db.get_series(conn, str(series_id), user_id=ctx.user_id)
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        episodes = stories_db.list_episodes(conn, str(series_id), user_id=ctx.user_id)
        liked = stories_db.is_liked(
            conn, user_id=ctx.user_id, content_type="series", content_id=str(series_id)
        )
        return SeriesDetail(**_ser(series), episode_count=len(episodes), liked=liked)
    finally:
        conn.close()


@router.get("/series/{series_id}/episodes", response_model=list[EpisodeSummary])
async def get_series_episodes(series_id: UUID, ctx: RequestContext = Depends(get_request_context)):
    conn = _connect()
    try:
        series = stories_db.get_series(conn, str(series_id), user_id=ctx.user_id)
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")
        episodes = stories_db.list_episodes(conn, str(series_id), user_id=ctx.user_id)
        return [EpisodeSummary(**_ser(e)) for e in episodes]
    finally:
        conn.close()


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[CategoryOut])
async def get_categories(ctx: RequestContext = Depends(get_request_context)):
    conn = _connect()
    try:
        return [CategoryOut(**c) for c in stories_db.list_categories(conn, user_id=ctx.user_id)]
    finally:
        conn.close()


# ── Search ────────────────────────────────────────────────────────────────────

@router.get("/search", response_model=SearchOut)
async def search(q: str = "", ctx: RequestContext = Depends(get_request_context)):
    if not q.strip():
        return SearchOut(films=[], series=[])
    conn = _connect()
    try:
        films = stories_db.search_films(conn, q, user_id=ctx.user_id)
        series = stories_db.search_series(conn, q, user_id=ctx.user_id)
        return SearchOut(
            films=[FilmSummary(**_ser(f)) for f in films],
            series=[SeriesSummary(**_ser(s)) for s in series],
        )
    finally:
        conn.close()


# ── Watch progress ────────────────────────────────────────────────────────────

@router.post("/progress", response_model=WatchProgressOut)
async def upsert_progress(
    body: WatchProgressIn,
    ctx: RequestContext = Depends(get_request_context),
):
    """Upsert watch progress. Completion is set when position >= 90 % of duration."""
    conn = _connect()
    try:
        row = stories_db.upsert_watch_progress(
            conn,
            user_id=ctx.user_id,
            content_type=body.content_type,
            content_id=str(body.content_id),
            position_seconds=body.position_seconds,
            duration_seconds=body.duration_seconds,
        )
        return WatchProgressOut(**_ser(row))
    finally:
        conn.close()


# ── Likes ─────────────────────────────────────────────────────────────────────

@router.post("/like", response_model=LikeOut)
async def toggle_like(
    body: LikeIn,
    ctx: RequestContext = Depends(get_request_context),
):
    conn = _connect()
    try:
        if body.liked:
            stories_db.like_content(
                conn,
                user_id=ctx.user_id,
                content_type=body.content_type,
                content_id=str(body.content_id),
            )
        else:
            stories_db.unlike_content(
                conn,
                user_id=ctx.user_id,
                content_type=body.content_type,
                content_id=str(body.content_id),
            )
        return LikeOut(content_type=body.content_type, content_id=body.content_id, liked=body.liked)
    finally:
        conn.close()


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusCountsOut)
async def get_status(ctx: RequestContext = Depends(get_request_context)):
    """Return generating/ready/failed counts for the requesting user's films and series."""
    conn = _connect()
    try:
        counts = stories_db.get_status_counts(conn, user_id=ctx.user_id)
        return StatusCountsOut(**counts)
    finally:
        conn.close()
