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

from private_internet.billing.plans import feature_enabled_for_user
from private_internet.content.asset_store import AssetStore
from private_internet.content.creator_selector import CreatorSelector
from private_internet.content.jobs.video_job import _select_topic, _fetch_research
from private_internet.content.video_assembler import assemble_video
from private_internet.content.video_generator import SceneScriptGenerator
from private_internet.content.stories.db import (
    insert_film,
    update_film_progress,
    update_film_status,
)
from private_internet.database import _connect

logger = logging.getLogger(__name__)

# 2:3 portrait aspect ratio for the film poster (768×1152)
_POSTER_WIDTH = 768
_POSTER_HEIGHT = 1152

# Duration targets (seconds) passed to the scene script generator.
STORIES_DURATION_TARGETS = {
    "short_film":    (360,  900),   # 6–15 minutes
    "feature":       (900,  2700),  # 15–45 minutes
    "episode_short": (360,  600),   # 6–10 minutes
    "episode_long":  (900,  1800),  # 15–30 minutes
}


async def _generate_poster(title: str, premise: Optional[str]) -> bytes:
    """Generate a 2:3 portrait poster via fal FLUX.

    Falls back to a designed on-brand portrait cover on any failure so the film
    row can still be marked 'ready' with a real poster.
    """
    from private_internet.content.cover_art import generate_cover

    prompt = (
        f"Cinematic movie poster for '{title}'. "
        f"{(premise or '')[:120]} "
        "Dark, moody, editorial photography style. Portrait orientation. No text."
    )
    # generate_cover never raises: fal FLUX with a designed portrait fallback.
    return await generate_cover(
        prompt,
        width=_POSTER_WIDTH,
        height=_POSTER_HEIGHT,
        fallback_title=title,
        kicker="STORIES",
        fallback_subtitle=(premise or "")[:60],
        seed=title,
    )


async def generate_film(
    *,
    user_id: str,
    title: str,
    premise: Optional[str] = None,
    category: Optional[str] = None,
    topic_id: Optional[str] = None,
    film_id: Optional[str] = None,
) -> str:
    """
    Generate a STORIES film via the scene-stitching pipeline.

    Steps:
    1. Reserve a stories_films row (status='generating') — unless `film_id` is
       supplied (the router pre-inserts one so the caller has an id to poll).
    2. Resolve a topic + creator + research (real topic if topic_id, else a
       synthetic topic from the title/premise).
    3. Generate a scene-by-scene script (SceneScriptGenerator) targeting the
       STORIES short_film duration band.
    4. assemble_video(): translate → N Kling clips (parallel, semaphored, with
       fallback cards) → ElevenLabs narration → FFmpeg stitch → S3. Progress is
       written to generation_progress after every clip.
    5. Generate a 2:3 portrait poster via fal FLUX (fallback: gradient).
    6. Update stories_films to status='ready' with all media URLs.

    On any failure the row is set to status='failed' and the exception re-raised.
    Returns the stories_films.id (UUID str).
    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any content operation"

    conn = _connect()
    # A dedicated connection for progress writes during the async clip fan-out,
    # so they never collide with the main connection's cursors.
    progress_conn = _connect()

    try:
        # 1. Reserve the film row (unless the caller already did).
        if film_id is None:
            film_id = insert_film(
                conn, user_id=user_id, title=title, premise=premise, category=category,
            )
        logger.info("[user:%s] STORIES film %s — starting generation (title=%r)", user_id[:8], film_id, title)

        # 2. Resolve topic + creator + research.
        if topic_id:
            topic = _select_topic(conn, topic_id, user_id=user_id)
            research = _fetch_research(conn, topic["id"], user_id=user_id)
        else:
            # Synthetic topic from the requested title/premise (no DB row).
            topic = {
                "id": None,
                "name": title,
                "keywords": [k.strip() for k in (premise or "").split(",") if k.strip()],
            }
            research = []
        creator = CreatorSelector().select_for_topic(conn, topic)

        # 3. Scene-by-scene script.
        duration_min, duration_max = STORIES_DURATION_TARGETS["short_film"]
        script = await SceneScriptGenerator().generate(
            topic, creator, research,
            duration_min=duration_min, duration_max=duration_max,
            content_label="short film",
        )
        logger.info(
            "[user:%s] STORIES film %s — script: %d scenes (~%ds)",
            user_id[:8], film_id, len(script.scenes), script.total_duration_seconds,
        )

        # 4. Assemble — progress written after every clip.
        def _on_progress(patch: dict) -> None:
            update_film_progress(progress_conn, film_id, patch, user_id=user_id)

        video_key = f"stories/{film_id}/film.mp4"
        await assemble_video(
            scenes=script.scenes,
            narration_text=script.narration_text,
            language_code="en",
            output_s3_key=video_key,
            content_type="stories",
            topic_name=topic["name"],
            on_progress=_on_progress,
        )

        # 5. Poster + media URLs.
        asset_store = AssetStore()
        poster_bytes = await _generate_poster(title, premise)
        poster_url = asset_store._upload(f"stories/{film_id}/poster.png", poster_bytes, "image/png")
        video_url = f"{asset_store.cdn_base}/{video_key}"

        # 6. Mark ready.
        update_film_status(
            conn,
            film_id,
            "ready",
            user_id=user_id,
            video_url=video_url,
            thumbnail_url=poster_url,
            poster_url=poster_url,
            duration_seconds=script.total_duration_seconds,
        )
        logger.info(
            "[user:%s] STORIES film %s ready — duration=%ds video=%s",
            user_id[:8], film_id, script.total_duration_seconds, video_url,
        )
        return film_id

    except Exception as exc:
        logger.error("[user:%s] STORIES film generation failed: %s", user_id[:8], exc, exc_info=True)
        if film_id:
            try:
                update_film_status(
                    conn, film_id, "failed", user_id=user_id, error_message=str(exc)[:512],
                )
            except Exception:
                logger.error("Could not mark film %s as failed", film_id, exc_info=True)
        raise

    finally:
        conn.close()
        progress_conn.close()


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
    # STORIES is a Max-only feature. The cron fan-out (run_for_all_users) calls
    # this for every onboarded user, so skip users whose plan doesn't include it.
    if not feature_enabled_for_user(user_id, "stories"):
        logger.info(f"[user:{user_id[:8]}] skipping STORIES films — plan lacks 'stories'")
        return {"generated": [], "failed": [], "skipped": "plan"}

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
