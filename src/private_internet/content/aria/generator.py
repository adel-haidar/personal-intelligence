"""ARIA music generation pipeline.

Pipeline per track:
  1. Fetch recent user memories (reuse memory service search).
  2. Bedrock metadata via forced tool_choice (temp=0, max_tokens=1024) →
     title, mood, genre, bpm, key, instruments, lyrics snippet.
  3. Suno music generation (suno_client, full-length track + min-duration check).
  4. compute_waveform → list[float].
  5. fal album art (fal_image.generate_image, 1024x1024).
  6. Upload audio + waveform.json + art to S3 via asset_store.
  7. Auto-group playlists by mood + "From your brain" catch-all (pure Python, no LLM).
  8. Write DB rows, set status='ready'/'failed'.

Max 2 concurrent tracks (asyncio.Semaphore, FFmpeg-adjacent CPU budget).
run_for_all_users-friendly: takes a required user_id, asserts it.

On failure: status='failed', log with [user:xxxxxxxx], no auto-retry.
"""

import asyncio
import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3

from private_internet.billing.plans import feature_enabled_for_user
from private_internet.config import get_settings
from private_internet.content.aria.db import (
    insert_track,
    update_track_status,
    upsert_playlist,
    add_tracks_to_playlist,
    list_tracks,
    list_playlists,
)
from private_internet.content.aria.suno_client import SunoClient
from private_internet.content.aria.waveform import compute_waveform
from private_internet.content.asset_store import AssetStore
from private_internet.content.fal_image import generate_image
from private_internet.content.llm import bedrock_text_region
from private_internet.database import _connect

logger = logging.getLogger(__name__)

_SEM = asyncio.Semaphore(2)

# Recency window we sample diversely from (vs. taking the newest N raw).
_MEMORY_SAMPLE_WINDOW = 200

# ── Bedrock tool schema (forced tool_choice, temperature=0) ───────────────────

_TRACK_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "A creative, evocative track title (max 60 chars).",
        },
        "mood": {
            "type": "string",
            "enum": ["calm", "focus", "energetic", "melancholic", "uplifting", "tense"],
            "description": "The dominant emotional mood of this track.",
        },
        "genre": {
            "type": "string",
            "description": "Musical genre (e.g. ambient, lo-fi, classical, electronic).",
        },
        "topic_category": {
            "type": "string",
            "description": "The broad life/knowledge category this music is for (e.g. 'work', 'health', 'finance', 'study').",
        },
        "bpm": {
            "type": "integer",
            "description": "Suggested beats per minute (40–200).",
        },
        "musical_key": {
            "type": "string",
            "description": "Musical key (e.g. 'C major', 'A minor').",
        },
        "instruments": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of primary instruments/sounds (2–6 items).",
        },
        "lyrics": {
            "type": "string",
            "description": "Optional short lyrical phrase or spoken intro (max 80 chars). Empty string if purely instrumental.",
        },
        "suno_style_prompt": {
            "type": "string",
            "description": (
                "Music generation style prompt for Suno AI. "
                "Format: '[genre], [mood], [key instruments], [tempo descriptor]'. "
                "Example: 'ambient piano, melancholic, strings, slow'. "
                "Maximum 200 characters. Musical terms only — no abstract concepts."
            ),
        },
        "make_instrumental": {
            "type": "boolean",
            "description": (
                "True for instrumental only. "
                "False only if lyrics were generated in this tool call."
            ),
        },
        "art_prompt": {
            "type": "string",
            "description": "A visual art prompt for the album cover image (60–200 chars). Abstract, no text.",
        },
    },
    "required": [
        "title", "mood", "genre", "topic_category", "bpm", "musical_key",
        "instruments", "lyrics", "suno_style_prompt", "make_instrumental", "art_prompt",
    ],
}

_SYSTEM_PROMPT = (
    "You are a music director for a private AI music platform. "
    "Given a user's recent memories and topics, design a personalised music track "
    "that reflects their current interests and emotional context. "
    "Be creative but grounded in the content. "
    "Use the tool to return structured metadata. "
    "Return only the tool call."
)


# ── Memory fetching ───────────────────────────────────────────────────────────

def _fetch_recent_memories(user_id: str, limit: int = 8) -> list[dict]:
    """Fetch a *topic-diverse* sample of the user's memories for track context.

    Pure recency (ORDER BY created_at DESC LIMIT n) biased every track toward
    whatever was added most recently — e.g. a burst of finance-agent test runs
    made every track "finance" while daily health summaries got buried. Instead
    we pull a larger recent window, bucket by the memory's primary tag, and
    round-robin across buckets (shuffled per call) so distinct themes (health,
    finance, …) are represented and successive tracks in a batch differ.

    Falls back to plain recency / empty list on error. # MUST SCOPE BY USER
    """
    try:
        from psycopg2.extras import RealDictCursor
        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT title, content, tags FROM memories
                   WHERE user_id = %s AND merged_into IS NULL
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, _MEMORY_SAMPLE_WINDOW),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
            conn.close()

        if len(rows) <= limit:
            return rows

        # Bucket by primary tag so a finance-heavy window cannot crowd out other
        # themes; untagged memories share one bucket so they don't dominate either.
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            first_tag = next(
                (t.strip().lower() for t in (r.get("tags") or "").split(",") if t.strip()),
                "__untagged__",
            )
            buckets.setdefault(first_tag, []).append(r)

        rnd = random.Random()
        order = list(buckets.keys())
        rnd.shuffle(order)
        for k in order:
            rnd.shuffle(buckets[k])

        # Round-robin one memory per bucket until we have `limit`.
        picked: list[dict] = []
        idx = 0
        while len(picked) < limit and any(buckets[k] for k in order):
            k = order[idx % len(order)]
            if buckets[k]:
                picked.append(buckets[k].pop())
            idx += 1
        return picked[:limit]
    except Exception as e:
        logger.warning("[user:%s] could not fetch memories: %s", user_id[:8], e)
        return []


# ── Bedrock metadata generation ───────────────────────────────────────────────

def _generate_track_metadata(memories: list[dict], user_id: str) -> dict:
    """Invoke Bedrock with forced tool_choice to get track metadata.
    temperature=0, max_tokens=1024. Synchronous — call via run_in_executor.
    """
    model_id = os.getenv(
        "BEDROCK_TEXT_MODEL_ID",
        "eu.anthropic.claude-3-5-haiku-20241022-v1:0",
    )
    # Build user message from memories.
    if memories:
        memory_text = "\n".join(
            f"- {m['title']}: {m['content'][:200]}" for m in memories[:8]
        )
        user_msg = (
            f"My recent memories and topics:\n{memory_text}\n\n"
            "Based on these, design a personalised music track for me."
        )
    else:
        user_msg = (
            "I have no recent memories loaded yet. "
            "Create a versatile, calming instrumental track suitable for focused work."
        )

    client = boto3.client("bedrock-runtime", region_name=bedrock_text_region())
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": user_msg}]}],
        system=[{"text": _SYSTEM_PROMPT}],
        inferenceConfig={"temperature": 0, "maxTokens": 1024},
        toolConfig={
            "tools": [{
                "toolSpec": {
                    "name": "generate_track_metadata",
                    "description": "Generate structured metadata for a personalised music track.",
                    "inputSchema": {"json": _TRACK_TOOL_SCHEMA},
                }
            }],
            "toolChoice": {"tool": {"name": "generate_track_metadata"}},
        },
    )
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise RuntimeError("Bedrock returned no tool call for track metadata")


# ── Asset store extensions ────────────────────────────────────────────────────

def _upload_aria_audio(store: AssetStore, audio_bytes: bytes, track_id: str) -> str:
    key = f"aria/tracks/{track_id}/audio.mp3"
    return store._upload(key, audio_bytes, "audio/mpeg")


def _upload_aria_waveform(store: AssetStore, bars: list[float], track_id: str) -> str:
    key = f"aria/tracks/{track_id}/waveform.json"
    body = json.dumps({"bars": bars}).encode()
    return store._upload(key, body, "application/json")


def _upload_aria_art(store: AssetStore, image_bytes: bytes, track_id: str) -> str:
    key = f"aria/tracks/{track_id}/art.png"
    return store._upload(key, image_bytes, "image/png")


def _s3_key_from_cdn(cdn_url: str, store: AssetStore) -> str:
    """Strip the CDN base from a CloudFront URL to get the S3 key."""
    base = store.cdn_base.rstrip("/")
    if cdn_url.startswith(base):
        return cdn_url[len(base):].lstrip("/")
    return cdn_url


# ── Auto-playlist grouping (pure Python, no LLM) ─────────────────────────────

def _auto_group_playlists(track_ids_by_mood: dict[str, list[str]], user_id: str) -> None:
    """
    Create/update mood-based auto-playlists and a single "From your brain" catch-all.
    All pure Python, no LLM calls. # MUST SCOPE BY USER
    """
    # Deterministic playlist IDs per user+mood so we upsert rather than duplicate.
    mood_labels = {
        "calm": "Calm & Peaceful",
        "focus": "Deep Focus",
        "energetic": "High Energy",
        "melancholic": "Melancholic",
        "uplifting": "Uplifting Vibes",
        "tense": "Tense & Dramatic",
    }
    for mood, tids in track_ids_by_mood.items():
        if not tids:
            continue
        # Stable UUID derived from user_id + mood string (deterministic) — used
        # only when no per-mood playlist exists yet. upsert_playlist reuses any
        # existing row's id (keyed on user_id+mood) and returns the canonical id
        # we must append tracks to.
        pl_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{user_id}:mood:{mood}"))
        canonical_id = upsert_playlist(
            playlist_id=pl_id,
            user_id=user_id,
            title=mood_labels.get(mood, mood.capitalize()),
            dominant_mood=mood,
            is_auto_generated=True,
        )
        add_tracks_to_playlist(canonical_id, tids, user_id=user_id)

    # "From your brain" — all ready tracks
    all_ids = [tid for tids in track_ids_by_mood.values() for tid in tids]
    if all_ids:
        brain_pl_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{user_id}:brain"))
        canonical_brain_id = upsert_playlist(
            playlist_id=brain_pl_id,
            user_id=user_id,
            title="From Your Brain",
            dominant_mood=None,
            is_auto_generated=True,
        )
        add_tracks_to_playlist(canonical_brain_id, all_ids, user_id=user_id)


# ── Single track generation ───────────────────────────────────────────────────

async def generate_track(*, user_id: str) -> str:
    """
    Generate one ARIA track for the given user. Returns the track_id.
    On any failure: sets status='failed', logs with [user:xxxxxxxx], re-raises.
    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any ARIA operation"

    track_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    store = AssetStore()
    t0 = datetime.now(timezone.utc)

    logger.info("[user:%s] ARIA: starting track %s", user_id[:8], track_id)

    # 1. Fetch memories (off event loop, blocking DB call).
    memories = await loop.run_in_executor(
        None, lambda: _fetch_recent_memories(user_id)
    )
    logger.info("[user:%s] ARIA: %d memories fetched", user_id[:8], len(memories))

    # 2. Bedrock metadata (blocking, off event loop).
    try:
        t_meta = datetime.now(timezone.utc)
        metadata = await loop.run_in_executor(
            None, lambda: _generate_track_metadata(memories, user_id)
        )
        logger.info(
            "[user:%s] ARIA: metadata in %.1fs — '%s' (%s)",
            user_id[:8],
            (datetime.now(timezone.utc) - t_meta).total_seconds(),
            metadata.get("title", "?"),
            metadata.get("mood", "?"),
        )
    except Exception as e:
        logger.error("[user:%s] ARIA: metadata generation failed: %s", user_id[:8], e, exc_info=True)
        raise

    # Insert the track row early (status=generating) so status polling works.
    await loop.run_in_executor(
        None,
        lambda: insert_track(
            user_id=user_id,
            track_id=track_id,
            title=metadata["title"],
            mood=metadata["mood"],
            genre=metadata.get("genre", ""),
            topic_category=metadata.get("topic_category", ""),
            lyrics=metadata.get("lyrics", ""),
            bpm=metadata.get("bpm"),
            musical_key=metadata.get("musical_key", ""),
            instruments=metadata.get("instruments", []),
        ),
    )

    suno_task_id: Optional[str] = None
    try:
        # 3. Music generation via Suno (full-length track; client polls + enforces
        #    the 120s minimum and retries once internally).
        t_music = datetime.now(timezone.utc)
        style_prompt = (
            metadata.get("suno_style_prompt")
            or metadata.get("music_prompt")
            or f"{metadata['mood']} {metadata.get('genre', 'ambient')}"
        )
        make_instrumental = metadata.get("make_instrumental", True)
        lyrics = metadata.get("lyrics", "") or ""
        suno = SunoClient()
        result = await suno.generate_with_min_duration(
            prompt=lyrics,
            style=style_prompt,
            title=metadata["title"],
            instrumental=make_instrumental,
        )
        audio_bytes = result.audio
        suno_task_id = result.task_id
        suno_duration = int(round(result.duration_seconds))
        logger.info(
            "[user:%s] ARIA: audio in %.1fs (%d bytes, %ds, job %s)",
            user_id[:8],
            (datetime.now(timezone.utc) - t_music).total_seconds(),
            len(audio_bytes),
            suno_duration,
            suno_task_id,
        )

        # 4. Waveform (CPU-bound pure Python, off event loop).
        bars = await loop.run_in_executor(
            None, lambda: compute_waveform(audio_bytes, num_bars=200)
        )
        logger.info("[user:%s] ARIA: waveform computed (%d bars)", user_id[:8], len(bars))

        # 5. Album art via fal.ai (async HTTP).
        art_bytes: Optional[bytes] = None
        art_prompt = metadata.get(
            "art_prompt",
            f"abstract album art, {metadata['mood']} mood, {metadata.get('genre','ambient')}, no text",
        )
        try:
            art_bytes = await generate_image(art_prompt, width=1024, height=1024)
            logger.info("[user:%s] ARIA: album art generated", user_id[:8])
        except Exception as art_err:
            logger.warning("[user:%s] ARIA: art generation failed (%s) — skipping", user_id[:8], art_err)

        # 6. Upload to S3.
        audio_cdn = _upload_aria_audio(store, audio_bytes, track_id)
        waveform_cdn = _upload_aria_waveform(store, bars, track_id)
        art_cdn: Optional[str] = None
        if art_bytes:
            art_cdn = _upload_aria_art(store, art_bytes, track_id)

        audio_key = _s3_key_from_cdn(audio_cdn, store)
        waveform_key = _s3_key_from_cdn(waveform_cdn, store)
        art_key = _s3_key_from_cdn(art_cdn, store) if art_cdn else None

        # Real duration measured by the Suno client (pydub); already validated ≥120s.
        duration_seconds = suno_duration

        # 7. Update DB: status=ready.
        await loop.run_in_executor(
            None,
            lambda: update_track_status(
                track_id,
                "ready",
                user_id=user_id,
                audio_s3_key=audio_key,
                waveform_s3_key=waveform_key,
                art_s3_key=art_key,
                duration_seconds=duration_seconds,
                suno_job_id=suno_task_id,
            ),
        )

        # 8. Auto-group playlists.
        await loop.run_in_executor(
            None,
            lambda: _auto_group_playlists(
                {metadata["mood"]: [track_id]},
                user_id,
            ),
        )

        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        logger.info(
            "[user:%s] ARIA: track %s ready in %.1fs — '%s'",
            user_id[:8], track_id, elapsed, metadata["title"],
        )
        return track_id

    except Exception as e:
        logger.error(
            "[user:%s] ARIA: track %s failed: %s", user_id[:8], track_id, e, exc_info=True
        )
        try:
            await loop.run_in_executor(
                None,
                lambda: update_track_status(track_id, "failed", user_id=user_id),
            )
        except Exception:
            logger.error("[user:%s] ARIA: could not mark track %s as failed", user_id[:8], track_id)
        raise


# ── Batch generation (semaphore-limited) ─────────────────────────────────────

async def generate_tracks_batch(count: int = 1, *, user_id: str) -> dict:
    """
    Generate `count` tracks for the user, at most 2 concurrently.
    Returns {"created": [track_id, ...], "failed": int}.
    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any ARIA operation"
    # ARIA is a Pro+ feature. The cron fan-out (run_for_all_users) calls this for
    # every onboarded user, so skip users whose plan doesn't include it.
    if not feature_enabled_for_user(user_id, "aria"):
        logger.info(f"[user:{user_id[:8]}] skipping ARIA tracks — plan lacks 'aria'")
        return {"created": [], "failed": 0, "skipped": "plan"}

    async def _one():
        async with _SEM:
            return await generate_track(user_id=user_id)

    created = []
    failed = 0
    tasks = [asyncio.create_task(_one()) for _ in range(count)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            failed += 1
        else:
            created.append(r)
    logger.info(
        "[user:%s] ARIA batch done — created: %d, failed: %d",
        user_id[:8], len(created), failed,
    )
    return {"created": created, "failed": failed}
