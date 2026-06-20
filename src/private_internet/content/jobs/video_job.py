"""SIGNAL video generation pipeline (Phase 4, Task 5)."""

import os
import uuid
import shutil
import asyncio
import logging
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from private_internet.billing.plans import feature_enabled_for_user
from private_internet.config import get_settings
from private_internet.database import _connect
from private_internet.content.creator_selector import CreatorSelector
from private_internet.content.video_generator import (
    VideoScriptGenerator,
    VideoImageGenerator,
    SceneScriptGenerator,
    SIGNAL_DURATION_TARGETS,
)
from private_internet.content.elevenlabs_engine import ElevenLabsEngine, get_tts_engine
from private_internet.content.fal_video import generate_video_clip
from private_internet.content.video_provider import get_provider
from private_internet.content.voice_config import get_voice_id
from private_internet.content.user_language import resolve_user_language
from private_internet.content.ffmpeg_assembler import VideoAssembler
from private_internet.content.video_assembler import assemble_video
from private_internet.content.asset_store import AssetStore
from private_internet.content.visual_translator import (
    build_final_prompt,
    kling_duration,
    translate_scenes,
)

logger = logging.getLogger(__name__)

# Spoken script targets ~90–120s; used as the translator's duration hint.
SIGNAL_TARGET_DURATION_S = 100


async def _section_visual(
    image_generator, section, creator, idx, title, work_dir, scene=None,
    content_type: str = "signal",
) -> str:
    """Per-section visual path: a generated fal video clip (.mp4) when
    VIDEO_BACKEND=fal AND a translated scene prompt is available AND the
    content_type's primary provider is 'kling', else a still image (.png).
    Any fal failure (incl. unfunded balance) falls back to a slide image,
    so the video always assembles.

    `scene` is a translated scene dict from the visual translation layer. Only
    its concrete `kling_prompt` (with the house style suffix) is ever sent to
    Kling — the abstract topic/script text never is. When no translated scene
    exists for this section we skip Kling entirely and render a slide.

    The Kling (fal) path is gated on `get_provider(content_type) == "kling"`:
    SIGNAL and PULSE are routed to WAN2 and must NEVER call generate_video_clip
    (Kling), even when VIDEO_BACKEND=fal.  Only STORIES (provider='kling') may
    enter the fal path here."""
    provider = get_provider(content_type)
    if scene and provider == "kling" and (get_settings().video_backend or "slides").lower() == "fal":
        try:
            prompt = build_final_prompt(scene)
            clip = await generate_video_clip(
                prompt, duration=kling_duration(scene), aspect_ratio="16:9"
            )
            path = os.path.join(work_dir, f"vis_{idx}.mp4")
            with open(path, "wb") as f:
                f.write(clip)
            return path
        except Exception as exc:
            logger.warning(
                "fal video failed for section %s (%s); slide fallback", idx, exc
            )
    img = await image_generator.generate_for_section(section, creator, title=title, index=idx)
    path = os.path.join(work_dir, f"vis_{idx}.png")
    with open(path, "wb") as f:
        f.write(img)
    return path


async def _translate_scenes_for_script(topic: dict, script) -> list:
    """Visual translation layer (Stage 3): turn the script into one concrete,
    filmable Kling scene per section. Returns a list aligned to script.sections
    where each entry is a translated scene dict or None (None → that section
    renders a slide instead of a Kling clip).

    Skipped (all None) for the slide backend, and degraded to all-None if the
    translator call fails — the pipeline always produces a video either way.
    """
    sections = script.sections
    scenes_by_section: list = [None] * len(sections)

    if (get_settings().video_backend or "slides").lower() != "fal":
        return scenes_by_section

    narration_script = " ".join(s.text for s in sections)
    try:
        scenes = await translate_scenes(
            topic=topic["name"],
            narration_script=narration_script,
            total_scenes=len(sections),
            target_duration_seconds=SIGNAL_TARGET_DURATION_S,
        )
    except Exception as exc:
        logger.warning(
            "Visual translation failed for topic=%r (%s); slides fallback",
            topic.get("name"), exc,
        )
        return scenes_by_section

    for scene in scenes:
        n = scene.get("scene_number")
        if not isinstance(n, int) or not (1 <= n <= len(sections)):
            continue
        scenes_by_section[n - 1] = scene
        # Log original + translated prompts for every scene — essential when a
        # clip still looks wrong.
        logger.debug(
            "Visual translation",
            extra={
                "scene_number": n,
                "original_topic": topic["name"][:100],
                "translated_prompt": scene.get("kling_prompt"),
                "final_prompt": build_final_prompt(scene),
            },
        )

    return scenes_by_section


def _select_topic(conn, topic_id: str | None, *, user_id: str) -> dict:
    """By id if given, else highest-weight topic without a video in the last 7 days.
    Always scoped to the user's own topics.  # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if topic_id:
            cur.execute(
                "SELECT * FROM content_topics WHERE id = %s AND user_id = %s",
                (topic_id, user_id),
            )
        else:
            cur.execute(
                """SELECT t.* FROM content_topics t
                   WHERE t.user_id = %s
                     AND NOT EXISTS (
                       SELECT 1 FROM content_videos v
                       WHERE v.topic_id = t.id
                         AND v.created_at >= now() - INTERVAL '7 days'
                   )
                   -- Prefer real (memory-derived) topics over onboarding seed topics.
                   ORDER BY (t.source = 'bootstrap') ASC, t.weight DESC, t.last_used_at ASC NULLS FIRST
                   LIMIT 1""",
                (user_id,),
            )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"No topic available for video generation (topic_id={topic_id!r})"
            )
        return dict(row)
    finally:
        cur.close()


def _fetch_research(conn, topic_id: str, *, user_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT * FROM content_research
               WHERE user_id = %s AND topic_id = %s
               ORDER BY fetched_at DESC LIMIT 5""",
            (user_id, topic_id),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


async def generate_video(topic_id: str | None = None, *, user_id: str) -> str:
    """
    Full SIGNAL pipeline for a single user: script → 5 slide images →
    Polly narration → FFmpeg assembly → S3/CloudFront. Returns the video_id.
    # MUST SCOPE BY USER

    On failure the content_videos row is set to status='failed' and the
    exception is re-raised. /tmp/{video_id} is cleaned up either way.
    """
    assert user_id is not None, "user_id must be set before any content operation"
    script_generator = VideoScriptGenerator()
    image_generator = VideoImageGenerator()
    tts = get_tts_engine()
    assembler = VideoAssembler()
    asset_store = AssetStore()

    conn = _connect()
    video_id = str(uuid.uuid4())
    work_dir = f"/tmp/{video_id}"

    try:
        # 1. Select topic + 2. creator
        topic = _select_topic(conn, topic_id, user_id=user_id)
        creator = CreatorSelector().select_for_topic(conn, topic)
        research = _fetch_research(conn, topic["id"], user_id=user_id)

        # Resolve user language once per video; all downstream steps share it.
        language_code = resolve_user_language(user_id)
        logger.info(
            f"Generating video {video_id} — topic='{topic['name']}', "
            f"creator='{creator['slug']}', language={language_code}"
        )

        # 3. Create the record up-front so the dashboard can show 'processing'
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO content_videos
               (id, creator_id, topic_id, title, script, status, user_id)
               VALUES (%s, %s, %s, %s, %s, 'processing', %s)""",
            (video_id, creator["id"], topic["id"], topic["name"], "", user_id),
        )
        conn.commit()
        cur.close()

        # 4. Script — generated in the user's resolved language.
        script = await script_generator.generate(topic, creator, research, language_code=language_code)
        os.makedirs(work_dir, exist_ok=True)

        # 4b. Visual scene translation (NEW). Convert the abstract topic/script
        # into concrete, filmable Kling prompts — one per section. The original
        # topic text is NEVER sent to Kling; only these translated prompts are.
        # Only needed for the fal video backend; the slide backend ignores it.
        scenes_by_section = await _translate_scenes_for_script(topic, script)

        # 5/6. Per-section visuals (fal video clip, or slide fallback) + thumbnail.
        # content_type="signal" ensures get_provider() gates the Kling path — SIGNAL
        # must never call generate_video_clip (Kling) regardless of VIDEO_BACKEND.
        visual_results = await asyncio.gather(
            *(
                _section_visual(
                    image_generator, s, creator, i, script.title, work_dir,
                    scenes_by_section[i],
                    content_type="signal",
                )
                for i, s in enumerate(script.sections)
            ),
            image_generator.generate_thumbnail(script, creator),
        )
        visual_paths, thumbnail_bytes = list(visual_results[:-1]), visual_results[-1]

        # 8/9. Narration via the configured TTS engine (sequential — TTS + ffprobe
        # are blocking, so run off the event loop).
        # ElevenLabs: pick the voice for the user's resolved language.
        # Polly: use the creator's configured voice when available; otherwise
        #   fall back to a language-matched voice (ElevenLabs _POLLY_VOICES map).
        loop = asyncio.get_event_loop()
        if isinstance(tts, ElevenLabsEngine):
            voice_id, lang_code = get_voice_id(language_code), language_code
        else:
            # Prefer the creator's native voice; it was auditioned for this creator.
            # If the creator was configured for a different language, the Polly
            # engine's engine-retry logic will still produce valid audio.
            voice_id, lang_code = creator["polly_voice_id"], creator["polly_language_code"]
        audio_paths = []
        for i, section in enumerate(script.sections):
            path = os.path.join(work_dir, f"audio_{i}.mp3")
            await loop.run_in_executor(
                None,
                lambda text=section.text, p=path: tts.synthesize_section(
                    text, voice_id, lang_code, p
                ),
            )
            audio_paths.append(path)

        # 10. Assemble (CPU-bound subprocess work — keep off the event loop)
        video_path = os.path.join(work_dir, "video.mp4")
        duration_seconds = await loop.run_in_executor(
            None,
            lambda: assembler.assemble(script.sections, visual_paths, audio_paths, video_path),
        )

        # 11/12. Upload to S3 → CloudFront URLs
        video_url = asset_store.upload_video(video_path, video_id)
        thumbnail_url = asset_store.upload_thumbnail(thumbnail_bytes, video_id)

        # 13/14. Finalize record + bump topic usage
        cur = conn.cursor()
        cur.execute(
            """UPDATE content_videos
               SET status = 'ready', title = %s, description = %s, script = %s,
                   video_url = %s, thumbnail_url = %s, duration_seconds = %s
               WHERE id = %s AND user_id = %s""",
            (
                script.title,
                script.description,
                script.to_json(),
                video_url,
                thumbnail_url,
                duration_seconds,
                video_id,
                user_id,
            ),
        )
        cur.execute(
            """UPDATE content_topics
               SET used_count = used_count + 1, last_used_at = %s
               WHERE id = %s AND user_id = %s""",
            (datetime.now(timezone.utc), topic["id"], user_id),
        )
        conn.commit()
        cur.close()

        logger.info(
            f"Video {video_id} ready — '{script.title}', {duration_seconds}s, {video_url}"
        )
        return video_id

    except Exception as e:
        logger.error(f"Video generation failed for {video_id}: {e}", exc_info=True)
        try:
            conn.rollback()
            cur = conn.cursor()
            cur.execute(
                "UPDATE content_videos SET status = 'failed' WHERE id = %s", (video_id,)
            )
            conn.commit()
            cur.close()
        except Exception:
            logger.error(f"Could not mark video {video_id} as failed", exc_info=True)
        raise

    finally:
        # 15. Cleanup even on failure
        shutil.rmtree(work_dir, ignore_errors=True)
        conn.close()


def _update_video_progress(conn, video_id: str, patch: dict, *, user_id: str) -> None:
    """Merge `patch` into a video's generation_progress JSONB. # MUST SCOPE BY USER"""
    import json
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE content_videos
               SET generation_progress = COALESCE(generation_progress, '{}'::jsonb) || %s::jsonb
               WHERE id = %s AND user_id = %s""",
            (json.dumps(patch), video_id, user_id),
        )
        conn.commit()
    finally:
        cur.close()


async def generate_long_video(
    topic_id: str | None = None, *, user_id: str, duration_band: str = "standard"
) -> str:
    """
    SIGNAL scene-stitching pipeline: scene-by-scene script → N video clips
    (per-provider routing in video_assembler — SIGNAL→Wan2.1, parallel,
    semaphored, colour-card fallback) → ElevenLabs narration → FFmpeg stitch →
    S3. Returns the video_id. # MUST SCOPE BY USER

    `duration_band` selects the SIGNAL_DURATION_TARGETS entry: "short" (~40s,
    ~5 clips — the cheap default for the scheduled feed) or "standard" (3–5 min).

    Unlike generate_video() (the 5-section slide pipeline), this assembles many
    short clips into one video via content/video_assembler.assemble_video.
    Per-clip progress is written to content_videos.generation_progress.

    On failure the row is set to status='failed' and the exception re-raised.
    """
    assert user_id is not None, "user_id must be set before any content operation"

    conn = _connect()
    progress_conn = _connect()  # dedicated conn for progress writes during fan-out
    video_id = str(uuid.uuid4())

    try:
        topic = _select_topic(conn, topic_id, user_id=user_id)
        creator = CreatorSelector().select_for_topic(conn, topic)
        research = _fetch_research(conn, topic["id"], user_id=user_id)

        # Resolve user language once per video; all downstream steps share it.
        language_code = resolve_user_language(user_id)
        logger.info(
            f"Generating long video {video_id} — topic='{topic['name']}', "
            f"creator='{creator['slug']}', language={language_code}"
        )

        cur = conn.cursor()
        cur.execute(
            """INSERT INTO content_videos
               (id, creator_id, topic_id, title, script, status, user_id)
               VALUES (%s, %s, %s, %s, %s, 'processing', %s)""",
            (video_id, creator["id"], topic["id"], topic["name"], "", user_id),
        )
        conn.commit()
        cur.close()

        # Scene-by-scene script targeting the requested SIGNAL duration band,
        # narrated in the user's resolved language.
        duration_min, duration_max = SIGNAL_DURATION_TARGETS[duration_band]
        script = await SceneScriptGenerator().generate(
            topic, creator, research,
            duration_min=duration_min, duration_max=duration_max,
            content_label="short video",
            language_code=language_code,
        )

        def _on_progress(patch: dict) -> None:
            _update_video_progress(progress_conn, video_id, patch, user_id=user_id)

        video_key = f"content/videos/{video_id}/video.mp4"
        await assemble_video(
            scenes=script.scenes,
            narration_text=script.narration_text,
            language_code=language_code,
            output_s3_key=video_key,
            content_type="signal",
            topic_name=topic["name"],
            on_progress=_on_progress,
        )
        video_url = f"{AssetStore().cdn_base}/{video_key}"

        cur = conn.cursor()
        cur.execute(
            """UPDATE content_videos
               SET status = 'ready', title = %s, video_url = %s, duration_seconds = %s
               WHERE id = %s AND user_id = %s""",
            (script.title, video_url, script.total_duration_seconds, video_id, user_id),
        )
        cur.execute(
            """UPDATE content_topics
               SET used_count = used_count + 1, last_used_at = %s
               WHERE id = %s AND user_id = %s""",
            (datetime.now(timezone.utc), topic["id"], user_id),
        )
        conn.commit()
        cur.close()

        logger.info(
            f"Long video {video_id} ready — '{script.title}', "
            f"{len(script.scenes)} scenes, {script.total_duration_seconds}s, {video_url}"
        )
        return video_id

    except Exception as e:
        logger.error(f"Long video generation failed for {video_id}: {e}", exc_info=True)
        try:
            conn.rollback()
            cur = conn.cursor()
            cur.execute(
                "UPDATE content_videos SET status = 'failed' WHERE id = %s", (video_id,)
            )
            conn.commit()
            cur.close()
        except Exception:
            logger.error(f"Could not mark video {video_id} as failed", exc_info=True)
        raise

    finally:
        conn.close()
        progress_conn.close()


async def generate_videos_batch(count: int = 2, topic_id: str | None = None, *, user_id: str) -> dict:
    """
    Run the standard-length WAN scene-stitching pipeline `count` times
    sequentially (not parallel — FFmpeg is CPU-bound) for a single user.
    A pinned topic_id only makes sense for a single video.  # MUST SCOPE BY USER

    Uses generate_long_video(duration_band="standard") → 3–5 min Wan2.1 clips
    (~€10–20/video, ~22–38 scenes) instead of the legacy fal/Kling+slide
    pipeline (generate_video, kept for pinned single-shot use).
    NOTE: "standard" is more expensive than the old "short" band (~5 clips).
    Use generate_long_video(duration_band="short") for cheap one-off tests.
    """
    assert user_id is not None, "user_id must be set before any content operation"
    # SIGNAL video is a Pro+ feature. The cron fan-out (run_for_all_users) calls
    # this for every onboarded user, so skip users whose plan doesn't include it.
    if not feature_enabled_for_user(user_id, "signal"):
        logger.info(f"[user:{user_id[:8]}] skipping SIGNAL videos — plan lacks 'signal'")
        return {"created": [], "failed": 0, "skipped": "plan"}
    if topic_id:
        count = 1
    created = []
    failed = 0
    for _ in range(count):
        try:
            created.append(
                await generate_long_video(
                    topic_id, user_id=user_id, duration_band="standard"
                )
            )
        except Exception:
            failed += 1
    logger.info(
        f"generate_videos_batch completed. Created: {len(created)}, Failed: {failed}"
    )
    return {"created": created, "failed": failed}
