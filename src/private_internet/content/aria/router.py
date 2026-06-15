"""ARIA API router — /api/aria endpoints.

All endpoints are scoped by the authenticated user via RequestContext
(same pattern as content/router.py). CloudFront URLs are derived from S3 keys
via the AssetStore cdn_base (NOT presigned URLs — consistent with the rest of
the repo).
# MUST SCOPE BY USER
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from private_internet.content.aria.db import (
    count_tracks,
    get_playlist,
    get_track,
    like_track,
    list_playlists,
    list_tracks,
    queue_next,
    record_play_end,
    record_play_start,
    search_tracks,
    unlike_track,
)
from private_internet.content.aria.generator import generate_tracks_batch
from private_internet.content.aria.podcast_db import (
    count_podcasts,
    get_podcast,
    like_podcast,
    list_podcasts,
    unlike_podcast,
)
from private_internet.content.aria.podcast_generator import generate_podcasts_batch
from private_internet.content.aria.podcast_models import (
    PodcastDetailOut,
    PodcastLikeRequest,
    PodcastLikeResponse,
    PodcastStatusOut,
    PodcastSummaryOut,
)
from private_internet.content.aria.models import (
    GenerationStatusOut,
    LibraryOut,
    LikeRequest,
    LikeResponse,
    PlayEndRequest,
    PlayEndRequest,
    PlayRequest,
    PlayResponse,
    PlaylistOut,
    QueueNextResponse,
    SearchResponse,
    TrackOut,
)
from private_internet.content.asset_store import AssetStore
from private_internet.content.router import _require_internal_secret
from private_internet.core.jobs import run_for_all_users
from private_internet.core.request_context import RequestContext, get_request_context

router = APIRouter(prefix="/api/aria")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cdn_base() -> str:
    store = AssetStore()
    return store.cdn_base.rstrip("/")


def _key_to_url(key: Optional[str]) -> Optional[str]:
    """Convert an S3 key to a CloudFront URL. Returns None if key is None/empty."""
    if not key:
        return None
    base = _cdn_base()
    return f"{base}/{key.lstrip('/')}"


def _track_row_to_out(row: dict) -> TrackOut:
    """Convert a DB row dict to TrackOut, replacing s3 keys with CDN URLs."""
    return TrackOut(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        title=row["title"],
        mood=row["mood"],
        genre=row.get("genre") or "",
        topic_category=row.get("topic_category") or "",
        duration_seconds=row.get("duration_seconds"),
        status=row["status"],
        audio_url=_key_to_url(row.get("audio_s3_key")),
        waveform_url=_key_to_url(row.get("waveform_s3_key")),
        art_url=_key_to_url(row.get("art_s3_key")),
        lyrics=row.get("lyrics"),
        bpm=row.get("bpm"),
        musical_key=row.get("musical_key"),
        instruments=list(row.get("instruments") or []),
        brain_topic_ids=[str(x) for x in (row.get("brain_topic_ids") or [])],
        is_liked=bool(row.get("is_liked", False)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _playlist_row_to_out(row: dict) -> PlaylistOut:
    tracks_out: Optional[list[TrackOut]] = None
    if "tracks" in row:
        tracks_out = [_track_row_to_out(t) for t in row["tracks"]]
    return PlaylistOut(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        title=row["title"],
        dominant_mood=row.get("dominant_mood"),
        art_url=_key_to_url(row.get("art_s3_key")),
        track_count=row.get("track_count", 0),
        total_duration=row.get("total_duration", 0),
        is_auto_generated=bool(row.get("is_auto_generated", False)),
        tracks=tracks_out,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _serialize_datetime(v):
    """Coerce datetime to isoformat string for logging; models handle it natively."""
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _podcast_summary_out(row: dict) -> PodcastSummaryOut:
    return PodcastSummaryOut(
        id=str(row["id"]),
        title=row["title"],
        description=row.get("description"),
        topic_category=row.get("topic_category"),
        duration_seconds=row.get("duration_seconds"),
        status=row["status"],
        art_url=_key_to_url(row.get("art_s3_key")),
        language_code=row.get("language_code") or "en",
        is_liked=bool(row.get("is_liked", False)),
        created_at=row["created_at"],
    )


def _podcast_detail_out(row: dict) -> PodcastDetailOut:
    return PodcastDetailOut(
        id=str(row["id"]),
        title=row["title"],
        description=row.get("description"),
        topic_category=row.get("topic_category"),
        duration_seconds=row.get("duration_seconds"),
        status=row["status"],
        art_url=_key_to_url(row.get("art_s3_key")),
        language_code=row.get("language_code") or "en",
        is_liked=bool(row.get("is_liked", False)),
        created_at=row["created_at"],
        audio_url=_key_to_url(row.get("audio_s3_key")),
        waveform_url=_key_to_url(row.get("waveform_s3_key")),
        transcript=row.get("transcript") or [],
        brain_topic_ids=[str(x) for x in (row.get("brain_topic_ids") or [])],
        host_a_name=row.get("host_a_name") or "Alex",
        host_b_name=row.get("host_b_name") or "Jordan",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/library", response_model=LibraryOut)
async def get_library(ctx: RequestContext = Depends(get_request_context)):
    """Full library: all ready tracks + all playlists for this user."""
    tracks = list_tracks(user_id=ctx.user_id, status="ready", limit=200)
    playlists = list_playlists(user_id=ctx.user_id)
    counts = count_tracks(user_id=ctx.user_id)
    liked_count = sum(
        1 for t in tracks if t.get("is_liked")
    )
    return LibraryOut(
        tracks=[_track_row_to_out(t) for t in tracks],
        playlists=[_playlist_row_to_out(p) for p in playlists],
        liked_count=liked_count,
        total_tracks=counts.get("ready", 0),
    )


@router.get("/tracks/{track_id}", response_model=TrackOut)
async def get_track_endpoint(
    track_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    row = get_track(track_id, user_id=ctx.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return _track_row_to_out(row)


@router.get("/playlists/{playlist_id}", response_model=PlaylistOut)
async def get_playlist_endpoint(
    playlist_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    row = get_playlist(playlist_id, user_id=ctx.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return _playlist_row_to_out(row)


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    ctx: RequestContext = Depends(get_request_context),
):
    rows = search_tracks(q, user_id=ctx.user_id)
    return SearchResponse(
        query=q,
        tracks=[_track_row_to_out(r) for r in rows],
    )


@router.post("/play", response_model=PlayResponse)
async def start_play(
    body: PlayRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Record the start of a play session. Returns play_id + track details."""
    row = get_track(body.track_id, user_id=ctx.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")
    play_id = body.play_id or str(uuid.uuid4())
    record_play_start(play_id, body.track_id, user_id=ctx.user_id)
    return PlayResponse(play_id=play_id, track=_track_row_to_out(row))


@router.post("/play-end", status_code=200)
async def end_play(
    body: PlayEndRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Record the end of a play session with duration."""
    if body.play_duration_seconds < 0:
        raise HTTPException(status_code=422, detail="play_duration_seconds must be >= 0")
    record_play_end(body.play_id, body.play_duration_seconds, user_id=ctx.user_id)
    return {"ok": True}


@router.post("/like", response_model=LikeResponse)
async def toggle_like(
    body: LikeRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Like or unlike a track."""
    row = get_track(body.track_id, user_id=ctx.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")
    if body.liked:
        like_track(body.track_id, user_id=ctx.user_id)
    else:
        unlike_track(body.track_id, user_id=ctx.user_id)
    return LikeResponse(track_id=body.track_id, liked=body.liked)


@router.get("/queue/next", response_model=QueueNextResponse)
async def get_queue_next(
    current_track_id: Optional[str] = None,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return the next track to play according to the four-tier queue rule."""
    next_track = queue_next(
        user_id=ctx.user_id,
        current_track_id=current_track_id,
    )
    if next_track is None:
        return QueueNextResponse(track=None, reason="no_tracks")

    # Determine which tier was used (informational).
    reason = "tier4_least_recently_played"
    if current_track_id and str(next_track.get("id")) != current_track_id:
        reason = "tier2_same_mood"
    return QueueNextResponse(
        track=_track_row_to_out(next_track),
        reason=reason,
    )


@router.get("/status", response_model=GenerationStatusOut)
async def get_generation_status(ctx: RequestContext = Depends(get_request_context)):
    """Generation status counts for this user."""
    counts = count_tracks(user_id=ctx.user_id)
    total = sum(counts.values())
    return GenerationStatusOut(
        generating=counts.get("generating", 0),
        ready=counts.get("ready", 0),
        failed=counts.get("failed", 0),
        total=total,
    )


@router.post("/jobs/generate", status_code=202)
async def trigger_generation(
    background_tasks: BackgroundTasks,
    count: int = Query(default=1, ge=1, le=5),
    ctx: RequestContext = Depends(get_request_context),
):
    """Trigger music generation for the authenticated user (1–5 tracks)."""
    background_tasks.add_task(generate_tracks_batch, count, user_id=ctx.user_id)
    return {"status": "enqueued", "count": count}


# ── Podcasts ────────────────────────────────────────────────────────────────

@router.get("/podcasts", response_model=list[PodcastSummaryOut])
async def list_podcasts_endpoint(ctx: RequestContext = Depends(get_request_context)):
    """All ready podcasts for this user (newest first)."""
    rows = list_podcasts(user_id=ctx.user_id, status="ready", limit=200)
    return [_podcast_summary_out(r) for r in rows]


@router.get("/podcasts/status", response_model=PodcastStatusOut)
async def podcast_status_endpoint(ctx: RequestContext = Depends(get_request_context)):
    """Generation status counts for frontend polling."""
    counts = count_podcasts(user_id=ctx.user_id)
    return PodcastStatusOut(
        generating=counts.get("generating", 0),
        failed=counts.get("failed", 0),
    )


@router.get("/podcasts/{podcast_id}", response_model=PodcastDetailOut)
async def get_podcast_endpoint(
    podcast_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Podcast detail: audio/waveform/art URLs + transcript + brain topics."""
    row = get_podcast(podcast_id, user_id=ctx.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Podcast not found")
    return _podcast_detail_out(row)


@router.post("/podcasts/{podcast_id}/like", response_model=PodcastLikeResponse)
async def like_podcast_endpoint(
    podcast_id: str,
    body: PodcastLikeRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    """Like or unlike a podcast."""
    row = get_podcast(podcast_id, user_id=ctx.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Podcast not found")
    if body.liked:
        like_podcast(podcast_id, user_id=ctx.user_id)
    else:
        unlike_podcast(podcast_id, user_id=ctx.user_id)
    return PodcastLikeResponse(podcast_id=podcast_id, liked=body.liked)


@router.post("/podcasts/jobs/generate", status_code=202)
async def trigger_podcast_generation(
    background_tasks: BackgroundTasks,
    count: int = Query(default=1, ge=1, le=2),
    ctx: RequestContext = Depends(get_request_context),
):
    """Trigger podcast generation for the authenticated user (1–2 episodes)."""
    background_tasks.add_task(generate_podcasts_batch, count, user_id=ctx.user_id)
    return {"status": "enqueued", "count": count}


@router.post("/podcasts/jobs/run", status_code=202)
async def run_podcast_generation_job_endpoint(
    background_tasks: BackgroundTasks,
    count: int = Query(default=2, ge=1, le=2),
    _: None = Depends(_require_internal_secret),
):
    """Internal-secret cron endpoint: generate up to `count` podcasts for ALL
    onboarded users (max 2 per user per run)."""
    background_tasks.add_task(run_for_all_users, generate_podcasts_batch, count=count)
    return {"status": "enqueued", "job": "podcast_generation", "count": count,
            "scope": "all_users"}


@router.post("/jobs/run", status_code=202)
async def run_music_generation_job_endpoint(
    background_tasks: BackgroundTasks,
    count: int = Query(default=2, ge=1, le=5),
    _: None = Depends(_require_internal_secret),
):
    """Internal-secret cron endpoint (systemd timer / EventBridge): generate
    `count` ARIA tracks for ALL onboarded users."""
    background_tasks.add_task(run_for_all_users, generate_tracks_batch, count=count)
    return {"status": "enqueued", "job": "music_generation", "count": count,
            "scope": "all_users"}
