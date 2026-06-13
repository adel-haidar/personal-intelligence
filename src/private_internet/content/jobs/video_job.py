"""SIGNAL video generation pipeline (Phase 4, Task 5)."""

import os
import uuid
import shutil
import asyncio
import logging
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect
from private_internet.content.creator_selector import CreatorSelector
from private_internet.content.video_generator import VideoScriptGenerator, VideoImageGenerator
from private_internet.content.polly_engine import PollyEngine
from private_internet.content.ffmpeg_assembler import VideoAssembler
from private_internet.content.asset_store import AssetStore

logger = logging.getLogger(__name__)


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
                   ORDER BY t.weight DESC, t.last_used_at ASC NULLS FIRST
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
    polly = PollyEngine()
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
        logger.info(
            f"Generating video {video_id} — topic='{topic['name']}', creator='{creator['slug']}'"
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

        # 4. Script
        script = await script_generator.generate(topic, creator, research)

        # 5/6. Slide images (parallel) + thumbnail
        image_results = await asyncio.gather(
            *(
                image_generator.generate_for_section(s, creator, title=script.title, index=i)
                for i, s in enumerate(script.sections)
            ),
            image_generator.generate_thumbnail(script, creator),
        )
        section_images, thumbnail_bytes = image_results[:-1], image_results[-1]

        # 7. Save images to the work dir (Nova Canvas outputs PNG)
        os.makedirs(work_dir, exist_ok=True)
        image_paths = []
        for i, image_bytes in enumerate(section_images):
            path = os.path.join(work_dir, f"img_{i}.png")
            with open(path, "wb") as f:
                f.write(image_bytes)
            image_paths.append(path)

        # 8/9. Narration — sequential, Polly rate limits. Polly + ffprobe are
        # blocking, so run off the event loop.
        loop = asyncio.get_event_loop()
        audio_paths = []
        for i, section in enumerate(script.sections):
            path = os.path.join(work_dir, f"audio_{i}.mp3")
            await loop.run_in_executor(
                None,
                lambda text=section.text, p=path: polly.synthesize_section(
                    text, creator["polly_voice_id"], creator["polly_language_code"], p
                ),
            )
            audio_paths.append(path)

        # 10. Assemble (CPU-bound subprocess work — keep off the event loop)
        video_path = os.path.join(work_dir, "video.mp4")
        duration_seconds = await loop.run_in_executor(
            None,
            lambda: assembler.assemble(script.sections, image_paths, audio_paths, video_path),
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


async def generate_videos_batch(count: int = 2, topic_id: str | None = None, *, user_id: str) -> dict:
    """
    Run generate_video() `count` times sequentially (not parallel — FFmpeg is
    CPU-bound) for a single user. A pinned topic_id only makes sense for a
    single video.  # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any content operation"
    if topic_id:
        count = 1
    created = []
    failed = 0
    for _ in range(count):
        try:
            created.append(await generate_video(topic_id, user_id=user_id))
        except Exception:
            failed += 1
    logger.info(
        f"generate_videos_batch completed. Created: {len(created)}, Failed: {failed}"
    )
    return {"created": created, "failed": failed}
