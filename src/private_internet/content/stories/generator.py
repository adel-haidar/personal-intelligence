"""STORIES film generator — reuses the SIGNAL video pipeline.

WHAT THIS FILE DOES
-------------------
Films are produced by calling the existing SIGNAL generate_video() function from
content/jobs/video_job.py. That function already handles:
  - topic selection / script via Bedrock Claude Haiku
  - per-section visuals (fal Kling clips or slide fallback)
  - ElevenLabs / Polly narration
  - FFmpeg assembly
  - S3 upload → CloudFront URL

After generate_video() returns a video_id we read the finished content_videos row
(where the video_url, thumbnail_url, and duration_seconds live), then add a 2:3
poster image via fal FLUX, and write the stories_films row.

STUBS
-----
Series / episode generation is STUBBED with a clear NotImplementedError. The data
model, router, and watch-progress logic are fully implemented for this minor version.
Real series generation requires multi-episode scripting (a future sprint).
"""

import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

from private_internet.content.asset_store import AssetStore
from private_internet.content.jobs.video_job import _select_topic, generate_video
from private_internet.content.stories.db import (
    insert_film,
    update_film_status,
)
from private_internet.database import _connect

logger = logging.getLogger(__name__)

# 2:3 portrait aspect ratio for the film poster (768×1152)
_POSTER_WIDTH = 768
_POSTER_HEIGHT = 1152


async def _generate_poster(title: str, premise: Optional[str]) -> bytes:
    """Generate a 2:3 portrait poster via fal FLUX.

    Falls back to a simple gradient poster on any failure so the film row can
    still be marked 'ready'.
    """
    from private_internet.content.fal_image import generate_image
    from private_internet.content.video_generator import _fallback_slide

    prompt = (
        f"Cinematic movie poster for '{title}'. "
        f"{(premise or '')[:120]} "
        "Dark, moody, editorial photography style. Portrait orientation. No text."
    )
    try:
        return await generate_image(
            prompt,
            width=_POSTER_WIDTH,
            height=_POSTER_HEIGHT,
            negative_text="text, watermark, logo, blurry, low quality",
        )
    except Exception as exc:
        logger.warning("Poster generation failed (%s); using gradient fallback.", exc)
        return _fallback_slide(_POSTER_WIDTH, _POSTER_HEIGHT, title)


async def generate_film(
    *,
    user_id: str,
    title: str,
    premise: Optional[str] = None,
    category: Optional[str] = None,
    topic_id: Optional[str] = None,
) -> str:
    """
    Generate a STORIES film by reusing the SIGNAL pipeline.

    Steps:
    1. Insert a stories_films row (status='generating') as a reservation.
    2. Call generate_video(topic_id, user_id=user_id) — this runs the full
       SIGNAL pipeline (script → visuals → TTS → FFmpeg → S3) and returns a
       content_videos.id.
    3. Read the finished content_videos row to get video_url, thumbnail_url,
       duration_seconds.
    4. Generate a 2:3 portrait poster via fal FLUX (fallback: gradient).
    5. Upload the poster to S3 under stories/{film_id}/poster.png.
    6. Update stories_films to status='ready' with all media URLs.

    On any failure:
    - The stories_films row is set to status='failed' with the error message.
    - The exception is re-raised so the caller / background task can surface it.

    Returns the stories_films.id (UUID str).
    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any content operation"

    conn = _connect()
    film_id: Optional[str] = None

    try:
        # 1. Reserve the film row in generating state
        film_id = insert_film(
            conn,
            user_id=user_id,
            title=title,
            premise=premise,
            category=category,
        )
        logger.info("[user:%s] STORIES film %s — starting generation (title=%r)", user_id[:8], film_id, title)

        # 2. Run SIGNAL pipeline — returns a content_videos.id
        video_id = await generate_video(topic_id, user_id=user_id)
        logger.info("[user:%s] STORIES film %s — SIGNAL video %s ready", user_id[:8], film_id, video_id)

        # 3. Read the completed content_videos row
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT video_url, thumbnail_url, duration_seconds FROM content_videos WHERE id = %s AND user_id = %s",
            (video_id, user_id),
        )
        video_row = cur.fetchone()
        cur.close()
        if not video_row:
            raise RuntimeError(f"content_videos row not found for video_id={video_id}")

        video_url = video_row["video_url"]
        thumbnail_url = video_row["thumbnail_url"]
        duration_seconds = video_row["duration_seconds"]

        # 4. Generate a 2:3 poster
        poster_bytes = await _generate_poster(title, premise)

        # 5. Upload poster
        asset_store = AssetStore()
        poster_key = f"stories/{film_id}/poster.png"
        # AssetStore._upload is the internal method used for all content types.
        # We call it directly with the correct key and content-type.
        poster_url = asset_store._upload(poster_key, poster_bytes, "image/png")

        # 6. Mark ready
        update_film_status(
            conn,
            film_id,
            "ready",
            user_id=user_id,
            signal_video_id=video_id,
            video_url=video_url,
            thumbnail_url=thumbnail_url,
            poster_url=poster_url,
            duration_seconds=duration_seconds,
        )
        logger.info(
            "[user:%s] STORIES film %s ready — duration=%.1fs video=%s",
            user_id[:8],
            film_id,
            duration_seconds or 0.0,
            video_url,
        )
        return film_id

    except Exception as exc:
        logger.error("[user:%s] STORIES film generation failed: %s", user_id[:8], exc, exc_info=True)
        if film_id:
            try:
                update_film_status(
                    conn,
                    film_id,
                    "failed",
                    user_id=user_id,
                    error_message=str(exc)[:512],
                )
            except Exception:
                logger.error("Could not mark film %s as failed", film_id, exc_info=True)
        raise

    finally:
        conn.close()


# ── Batch entry point (cron / run_for_all_users) ─────────────────────────────

async def generate_films_batch(count: int = 1, *, user_id: str) -> dict:
    """Generate `count` STORIES films for a single user, auto-selecting topics.

    Cron / ``run_for_all_users``-friendly: takes a required ``user_id`` and
    asserts it. Each film reuses the SIGNAL video pipeline via ``generate_film``;
    the title/premise are derived from the user's highest-weight unused topic
    (the same selector the SIGNAL video job uses), so no client input is needed.

    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any content operation"

    generated: list[str] = []
    failed: list[str] = []

    for _ in range(max(1, count)):
        # Pick a topic up-front so the film title matches the SIGNAL video's topic.
        conn = _connect()
        try:
            topic = _select_topic(conn, None, user_id=user_id)
        except Exception as exc:
            logger.warning(
                "[user:%s] STORIES batch — no topic available, stopping: %s",
                user_id[:8], exc,
            )
            break
        finally:
            conn.close()

        keywords = topic.get("keywords") or []
        premise = ", ".join(keywords) if keywords else None
        try:
            film_id = await generate_film(
                user_id=user_id,
                title=topic["name"],
                premise=premise,
                topic_id=str(topic["id"]),
            )
            generated.append(film_id)
        except Exception as exc:
            logger.error(
                "[user:%s] STORIES batch film failed: %s",
                user_id[:8], exc, exc_info=True,
            )
            failed.append(str(exc)[:200])

    return {"generated": generated, "failed": failed, "count": len(generated)}


# ── Series / episode generation (STUB) ───────────────────────────────────────

async def generate_series_episode(
    *,
    user_id: str,
    series_id: str,
    season_number: int,
    episode_number: int,
) -> str:
    """
    STUB — series/episode generation is not implemented in this minor version.

    The data model (stories_series, stories_episodes) and the corresponding API
    endpoints (GET /series/{id}, GET /series/{id}/episodes) are fully functional.
    Only the generation step is deferred.

    When this is implemented, each episode will:
    1. Generate a per-episode SIGNAL video (possibly with a series-aware prompt).
    2. Insert/update the stories_episodes row.
    3. Update stories_series.status to 'ready' once all episodes are done.
    """
    raise NotImplementedError(
        "Series/episode generation is not yet implemented. "
        "Create episodes manually via the DB layer or wait for the next sprint."
    )
