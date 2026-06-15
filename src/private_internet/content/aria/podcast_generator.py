"""ARIA podcast generation pipeline — two-host AI podcasts from brain memory.

Pipeline per episode:
  1. Fetch a brain memory cluster (recent memories incl. their language).
  2. Resolve the cluster's dominant language (resolve_dominant_language).
  3. Bedrock Claude writes a two-host dialogue script (forced tool schema).
  4. ElevenLabs TTS per line — SEQUENTIAL, 300ms sleep between calls (rate limits).
     Host A and Host B use distinct voices + distinct voice settings.
  5. FFmpeg interleaves the lines with natural silence gaps.
  6. (Optional) background ambient music mixed in at ~-22dB. Optional — never blocks.
  7. compute_waveform (same 200-float format as music tracks).
  8. fal album art from the script's art_prompt.
  9. Upload audio + waveform + art to S3; transcript stored as JSONB in the DB.

Short podcasts (< 8 min) are SAVED with a warning, never rejected — dialogue
length is bounded by the memory cluster's depth.

run_for_all_users-friendly: takes a required user_id, asserts it.
# MUST SCOPE BY USER
"""

import asyncio
import io
import json
import logging
import os
import subprocess
import tempfile
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3

from private_internet.config import get_settings
from private_internet.content.aria.music_client import generate_music
from private_internet.content.aria.podcast_db import (
    insert_podcast,
    update_podcast_status,
)
from private_internet.content.aria.voice_config import (
    DEFAULT_HOST_A_NAME,
    DEFAULT_HOST_B_NAME,
    get_podcast_voice_id,
    podcast_voices_configured,
    voice_settings_for_host,
)
from private_internet.content.aria.waveform import compute_waveform
from private_internet.content.asset_store import AssetStore
from private_internet.content.fal_image import generate_image
from private_internet.content.language_resolver import resolve_dominant_language
from private_internet.content.llm import bedrock_text_region
from private_internet.content.voice_config import language_name
from private_internet.database import _connect

logger = logging.getLogger(__name__)

# Two podcasts at most per generation run; the dialogue makes many TTS calls.
_SEM = asyncio.Semaphore(2)

# Valid pause durations (ms). Mirrors the tool schema enum + the silence files.
PAUSE_DURATIONS_MS = [100, 400, 600, 1200]

# Background music bed volume (~-22dB). Barely perceptible warmth.
_BACKGROUND_VOLUME = 0.08

# Below this many seconds we warn but still save (not a failure).
_MIN_DURATION_SECONDS = 480

_TTS_URL = (
    "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    "?output_format=mp3_44100_128"
)


# ── Stage 1: dialogue script generation (Bedrock Claude) ──────────────────────

PODCAST_SYSTEM_PROMPT = """
You are writing a script for a two-host podcast. The hosts are:
- Host A ({host_a_name}): analytical, asks precise questions,
  brings in data and historical context. Skeptical but fair.
- Host B ({host_b_name}): intuitive, connects ideas across domains,
  challenges assumptions, brings in human stories and implications.
  Enthusiastic but rigorous.

The podcast topic is derived from the user's personal memory brain.
The conversation must feel genuinely unscripted — hosts disagree,
build on each other's points, occasionally interrupt, and change
direction when something interesting emerges.

Rules:
- Target length: 8–12 minutes of audio (approximately 1,200–1,800 words)
- Structure: cold open (30s) → intro (1 min) → main discussion (6–8 min)
  → one disagreement or challenge moment → resolution → closing (1 min)
- Each individual line: 1–4 sentences. No monologues over 5 sentences.
- The cold open must start in the middle of something — not with
  "Welcome to the show" or "Today we're going to discuss".
- At least one moment where Host B challenges something Host A said.
- At least one specific example, story, or data point per topic segment.
- End with one open question the listener is left thinking about.
- Never use the word "fascinating" or "absolutely".
- Never have a host say "great question".
- Write the entire dialogue in {language_name}. Not English unless
  {language_name} is English.
""".strip()

# JSON schema for the forced tool. Anthropic-style input_schema; passed to
# Bedrock converse as inputSchema.json (same wrapper as aria/generator.py).
PODCAST_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "episode_title": {"type": "string"},
        "episode_description": {
            "type": "string",
            "description": "2-sentence episode summary for display",
        },
        "art_prompt": {
            "type": "string",
            "description": (
                "Abstract square image prompt for podcast episode art. "
                "Evoke the topic mood. No people. No microphones. "
                "No recording equipment. Abstract, atmospheric."
            ),
        },
        "topic_category": {
            "type": "string",
            "description": "Broad life/knowledge category (e.g. 'work', 'health').",
        },
        "dialogue": {
            "type": "array",
            "minItems": 30,
            "items": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "enum": ["A", "B"]},
                    "text": {
                        "type": "string",
                        "description": "What this host says. 1–4 sentences.",
                    },
                    "pause_after_ms": {
                        "type": "integer",
                        "description": (
                            "Silence after this line in milliseconds. "
                            "Normal turn: 400. After a question: 600. "
                            "Interruption or quick pickup: 100. Segment break: 1200."
                        ),
                        "enum": [100, 400, 600, 1200],
                    },
                },
                "required": ["host", "text", "pause_after_ms"],
            },
        },
        "closing_question": {
            "type": "string",
            "description": "The open question left for the listener",
        },
    },
    "required": [
        "episode_title", "episode_description", "art_prompt",
        "dialogue", "closing_question",
    ],
}


def _fetch_memory_cluster(user_id: str, limit: int = 12) -> list[dict]:
    """Fetch a recent memory cluster (id, title, content, language) for context.
    Falls back to an empty list on error. # MUST SCOPE BY USER"""
    try:
        from psycopg2.extras import RealDictCursor

        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT id, title, content, language FROM memories
                   WHERE user_id = %s AND merged_into IS NULL
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.warning("[user:%s] podcast: could not fetch memories: %s", user_id[:8], e)
        return []


def _generate_script(
    memories: list[dict],
    *,
    language_code: str,
    host_a_name: str,
    host_b_name: str,
    user_id: str,
) -> dict:
    """Invoke Bedrock with a forced tool to produce the dialogue script.

    Creative content (not deterministic) — uses a modest temperature. Synchronous;
    call via run_in_executor.
    """
    model_id = os.getenv(
        "BEDROCK_TEXT_MODEL_ID",
        "eu.anthropic.claude-3-5-haiku-20241022-v1:0",
    )
    lang_name = language_name(language_code)
    system_prompt = PODCAST_SYSTEM_PROMPT.format(
        host_a_name=host_a_name,
        host_b_name=host_b_name,
        language_name=lang_name,
    )

    if memories:
        memory_text = "\n".join(
            f"- {m.get('title') or 'Untitled'}: {(m.get('content') or '')[:300]}"
            for m in memories[:12]
        )
        user_msg = (
            f"Here is a cluster of my personal memories:\n{memory_text}\n\n"
            "Write a two-host podcast episode exploring the themes in these memories."
        )
    else:
        user_msg = (
            "I have no memories loaded yet. Write a two-host podcast episode about "
            "the value of keeping a personal knowledge brain and how reflection "
            "compounds over time."
        )

    client = boto3.client("bedrock-runtime", region_name=bedrock_text_region())
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": user_msg}]}],
        system=[{"text": system_prompt}],
        inferenceConfig={"temperature": 0.8, "maxTokens": 4096},
        toolConfig={
            "tools": [{
                "toolSpec": {
                    "name": "generate_podcast_script",
                    "description": "Generate a two-host podcast dialogue script.",
                    "inputSchema": {"json": PODCAST_SCRIPT_SCHEMA},
                }
            }],
            "toolChoice": {"tool": {"name": "generate_podcast_script"}},
        },
    )
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise RuntimeError("Bedrock returned no tool call for podcast script")


# ── Stage 3: audio generation per dialogue line ───────────────────────────────

def _synthesize_line(
    text: str,
    voice_id: str,
    *,
    stability: float,
    similarity_boost: float,
    model_id: str,
) -> bytes:
    """Synchronous ElevenLabs TTS for one line. Returns mp3 bytes.

    Mirrors content/elevenlabs_engine.py's urllib pattern. Call via executor.
    """
    s = get_settings()
    if not s.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")
    body = json.dumps({
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
        },
    }).encode()
    req = urllib.request.Request(
        _TTS_URL.format(voice_id=voice_id),
        data=body,
        headers={
            "xi-api-key": s.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


async def generate_dialogue_audio(
    dialogue: list[dict],
    language_code: str,
) -> list[tuple[bytes, int]]:
    """Generate audio for each line SEQUENTIALLY (never parallel — rate limits).

    Returns a list of (mp3_bytes, pause_after_ms) tuples, in dialogue order.
    """
    loop = asyncio.get_event_loop()
    result: list[tuple[bytes, int]] = []
    for line in dialogue:
        host_key = "host_a" if line["host"] == "A" else "host_b"
        voice_id = get_podcast_voice_id(host_key, language_code)
        settings = voice_settings_for_host(line["host"])
        mp3_bytes = await loop.run_in_executor(
            None,
            lambda l=line, v=voice_id, st=settings: _synthesize_line(
                l["text"],
                v,
                stability=st["stability"],
                similarity_boost=st["similarity_boost"],
                model_id="eleven_multilingual_v2",
            ),
        )
        pause = line.get("pause_after_ms", 400)
        if pause not in PAUSE_DURATIONS_MS:
            pause = 400
        result.append((mp3_bytes, pause))
        await asyncio.sleep(0.3)  # rate limit protection
    return result


# ── Stage 4: assembly with FFmpeg ─────────────────────────────────────────────

def _run_ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.error("FFmpeg failed: %s\n%s", " ".join(args), stderr[-2000:])
        raise RuntimeError(f"FFmpeg command failed: {stderr[-2000:]}") from e


def _generate_silence_files(tmp_dir: Path) -> dict[int, Path]:
    """Create one silence mp3 per unique pause duration. Returns {ms: path}."""
    paths: dict[int, Path] = {}
    for duration_ms in PAUSE_DURATIONS_MS:
        out = tmp_dir / f"silence_{duration_ms}ms.mp3"
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration_ms / 1000),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out),
        ])
        paths[duration_ms] = out
    return paths


def _build_concat_manifest(
    dialogue_audio: list[tuple[bytes, int]],
    line_paths: list[Path],
    tmp_dir: Path,
) -> str:
    """Build the ffmpeg concat manifest text, interleaving lines and silences.

    Each line is followed by a silence file matching its pause_after_ms. Pure
    string construction (no I/O) so it is unit-testable.
    """
    lines: list[str] = []
    for i, (_, pause_ms) in enumerate(dialogue_audio):
        lines.append(f"file '{line_paths[i]}'")
        lines.append(f"file '{tmp_dir}/silence_{pause_ms}ms.mp3'")
    return "\n".join(lines) + "\n"


async def assemble_podcast(
    dialogue_audio: list[tuple[bytes, int]],
    background_music_bytes: Optional[bytes],
    output_path: Path,
) -> None:
    """Interleave dialogue lines with silence gaps; optionally mix quiet
    background music. Writes the assembled MP3 to `output_path`."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _assemble_podcast_sync(
            dialogue_audio, background_music_bytes, output_path
        ),
    )


def _assemble_podcast_sync(
    dialogue_audio: list[tuple[bytes, int]],
    background_music_bytes: Optional[bytes],
    output_path: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="podcast_assembly_") as td:
        tmp_dir = Path(td)

        # 1. Write each dialogue mp3 to a temp file.
        line_paths: list[Path] = []
        for i, (mp3_bytes, _) in enumerate(dialogue_audio):
            p = tmp_dir / f"line_{i:04d}.mp3"
            p.write_bytes(mp3_bytes)
            line_paths.append(p)

        # 2. Silence files per unique pause duration.
        _generate_silence_files(tmp_dir)

        # 3. Concat manifest interleaving lines and silences.
        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text(
            _build_concat_manifest(dialogue_audio, line_paths, tmp_dir)
        )

        # 4. Concatenate into dialogue_raw.mp3.
        dialogue_raw = tmp_dir / "dialogue_raw.mp3"
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(dialogue_raw),
        ])

        # 5. Mix background music if provided. On any failure, fall back to the
        #    dialogue-only mix — never block.
        final_src = dialogue_raw
        if background_music_bytes:
            try:
                bg_path = tmp_dir / "background.mp3"
                bg_path.write_bytes(background_music_bytes)
                mixed = tmp_dir / "podcast_final.mp3"
                _run_ffmpeg([
                    "ffmpeg", "-y",
                    "-i", str(dialogue_raw),
                    "-i", str(bg_path),
                    "-filter_complex",
                    f"[1:a]volume={_BACKGROUND_VOLUME}[bg];"
                    f"[0:a][bg]amix=inputs=2:duration=first[out]",
                    "-map", "[out]",
                    "-c:a", "libmp3lame", "-b:a", "192k",
                    str(mixed),
                ])
                final_src = mixed
            except Exception as e:
                logger.warning("podcast: background mix failed (%s) — dialogue only", e)
                final_src = dialogue_raw

        # Move the chosen mix to the requested output path.
        Path(output_path).write_bytes(final_src.read_bytes())


# ── Duration helper ───────────────────────────────────────────────────────────

def get_audio_duration_seconds(mp3_bytes: bytes) -> float:
    """Duration of mp3 bytes in seconds, via pydub (ffprobe fallback). 0.0 on failure."""
    try:
        from pydub import AudioSegment

        seg = AudioSegment.from_file(io.BytesIO(mp3_bytes))
        return len(seg) / 1000.0
    except Exception as e:
        logger.debug("pydub duration failed (%s), trying ffprobe", e)
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
            f.write(mp3_bytes)
            f.flush()
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", f.name],
                check=True, capture_output=True,
            )
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception as e:
        logger.warning("podcast: could not measure duration (%s)", e)
        return 0.0


# ── S3 upload helpers ─────────────────────────────────────────────────────────

def _upload_audio(store: AssetStore, audio_bytes: bytes, podcast_id: str) -> str:
    return store._upload(f"aria/podcasts/{podcast_id}/audio.mp3", audio_bytes, "audio/mpeg")


def _upload_waveform(store: AssetStore, bars: list[float], podcast_id: str) -> str:
    body = json.dumps({"bars": bars}).encode()
    return store._upload(f"aria/podcasts/{podcast_id}/waveform.json", body, "application/json")


def _upload_art(store: AssetStore, image_bytes: bytes, podcast_id: str) -> str:
    return store._upload(f"aria/podcasts/{podcast_id}/art.png", image_bytes, "image/png")


def _s3_key_from_cdn(cdn_url: str, store: AssetStore) -> str:
    base = store.cdn_base.rstrip("/")
    if cdn_url.startswith(base):
        return cdn_url[len(base):].lstrip("/")
    return cdn_url


# ── Background music (optional) ───────────────────────────────────────────────

def _generate_background_bed(art_prompt: str) -> Optional[bytes]:
    """Best-effort ambient background bed via the music client. Never raises."""
    try:
        prompt = (
            "soft ambient background pad, minimal, unobtrusive, low volume, "
            "no drums, no melody, gentle texture for spoken-word podcast"
        )
        return generate_music(prompt)
    except Exception as e:
        logger.warning("podcast: background music generation failed (%s)", e)
        return None


# ── Single podcast generation ─────────────────────────────────────────────────

async def generate_podcast(*, user_id: str) -> Optional[str]:
    """Generate one ARIA podcast for the user. Returns the podcast_id, or None
    when generation is skipped (voices unconfigured / no ElevenLabs key).
    On failure after the row is created: status='failed', re-raises.
    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any ARIA operation"

    settings = get_settings()
    if not podcast_voices_configured():
        logger.warning(
            "[user:%s] podcast: voices not configured (placeholder IDs) — skipping",
            user_id[:8],
        )
        return None
    if not settings.elevenlabs_api_key:
        logger.warning("[user:%s] podcast: no ELEVENLABS_API_KEY — skipping", user_id[:8])
        return None

    podcast_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    store = AssetStore()
    t0 = datetime.now(timezone.utc)
    host_a_name, host_b_name = DEFAULT_HOST_A_NAME, DEFAULT_HOST_B_NAME

    logger.info("[user:%s] podcast: starting %s", user_id[:8], podcast_id)

    # 1. Fetch the memory cluster.
    memories = await loop.run_in_executor(None, lambda: _fetch_memory_cluster(user_id))

    # 2. Resolve the dominant language of the cluster (fallback English).
    language_code = resolve_dominant_language(memories, "en")
    logger.info(
        "[user:%s] podcast: %d memories, language=%s",
        user_id[:8], len(memories), language_code,
    )

    # 3. Bedrock dialogue script.
    try:
        script = await loop.run_in_executor(
            None,
            lambda: _generate_script(
                memories,
                language_code=language_code,
                host_a_name=host_a_name,
                host_b_name=host_b_name,
                user_id=user_id,
            ),
        )
    except Exception as e:
        logger.error("[user:%s] podcast: script generation failed: %s", user_id[:8], e, exc_info=True)
        raise

    dialogue = script.get("dialogue") or []
    title = script.get("episode_title", "Untitled Episode")
    brain_topic_ids = [str(m["id"]) for m in memories if m.get("id")]

    # Insert the row early (status=generating) so status polling works.
    await loop.run_in_executor(
        None,
        lambda: insert_podcast(
            user_id=user_id,
            podcast_id=podcast_id,
            title=title,
            description=script.get("episode_description", ""),
            topic_category=script.get("topic_category", ""),
            transcript=dialogue,
            brain_topic_ids=brain_topic_ids,
            host_a_name=host_a_name,
            host_b_name=host_b_name,
            language_code=language_code,
        ),
    )

    try:
        # 4. Dialogue audio (sequential ElevenLabs TTS).
        t_tts = datetime.now(timezone.utc)
        dialogue_audio = await generate_dialogue_audio(dialogue, language_code)
        logger.info(
            "[user:%s] podcast: %d lines synthesized in %.1fs",
            user_id[:8], len(dialogue_audio),
            (datetime.now(timezone.utc) - t_tts).total_seconds(),
        )

        # 5/6. Optional background bed + assembly.
        background = await loop.run_in_executor(
            None, lambda: _generate_background_bed(script.get("art_prompt", ""))
        )
        with tempfile.TemporaryDirectory(prefix="podcast_") as td:
            final_path = Path(td) / "podcast_final.mp3"
            await assemble_podcast(dialogue_audio, background, final_path)
            final_bytes = final_path.read_bytes()

        # Minimum duration — warn but never reject.
        duration = get_audio_duration_seconds(final_bytes)
        if duration < _MIN_DURATION_SECONDS:
            logger.warning(
                "[user:%s] podcast %s duration %.0fs is below the 8-minute target. "
                "Saving anyway — script may have been short.",
                user_id[:8], podcast_id, duration,
            )

        # 7. Waveform (same 200-float format as music tracks).
        bars = await loop.run_in_executor(
            None, lambda: compute_waveform(final_bytes, num_bars=200)
        )

        # 8. Episode art (fal.ai, 1:1). Best-effort.
        art_bytes: Optional[bytes] = None
        try:
            art_bytes = await generate_image(
                script.get("art_prompt", "abstract atmospheric texture, no text"),
                width=1024, height=1024,
            )
        except Exception as art_err:
            logger.warning("[user:%s] podcast: art generation failed (%s)", user_id[:8], art_err)

        # 9. Upload audio + waveform + art.
        audio_cdn = _upload_audio(store, final_bytes, podcast_id)
        waveform_cdn = _upload_waveform(store, bars, podcast_id)
        art_cdn = _upload_art(store, art_bytes, podcast_id) if art_bytes else None

        await loop.run_in_executor(
            None,
            lambda: update_podcast_status(
                podcast_id,
                "ready",
                user_id=user_id,
                audio_s3_key=_s3_key_from_cdn(audio_cdn, store),
                waveform_s3_key=_s3_key_from_cdn(waveform_cdn, store),
                art_s3_key=_s3_key_from_cdn(art_cdn, store) if art_cdn else None,
                duration_seconds=int(round(duration)),
            ),
        )

        logger.info(
            "[user:%s] podcast %s ready in %.1fs — '%s'",
            user_id[:8], podcast_id,
            (datetime.now(timezone.utc) - t0).total_seconds(), title,
        )
        return podcast_id

    except Exception as e:
        logger.error("[user:%s] podcast %s failed: %s", user_id[:8], podcast_id, e, exc_info=True)
        try:
            await loop.run_in_executor(
                None, lambda: update_podcast_status(podcast_id, "failed", user_id=user_id)
            )
        except Exception:
            logger.error("[user:%s] podcast: could not mark %s failed", user_id[:8], podcast_id)
        raise


# ── Batch generation (max 2 per run) ──────────────────────────────────────────

async def generate_podcasts_batch(count: int = 2, *, user_id: str) -> dict:
    """Generate up to `count` podcasts (hard-capped at 2 per run to control
    ElevenLabs usage). Returns {"created": [...], "failed": int, "skipped": int}.
    # MUST SCOPE BY USER
    """
    assert user_id is not None, "user_id must be set before any ARIA operation"
    count = max(1, min(count, 2))

    async def _one():
        async with _SEM:
            return await generate_podcast(user_id=user_id)

    created: list[str] = []
    failed = 0
    skipped = 0
    results = await asyncio.gather(
        *[asyncio.create_task(_one()) for _ in range(count)],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            failed += 1
        elif r is None:
            skipped += 1
        else:
            created.append(r)
    logger.info(
        "[user:%s] podcast batch — created: %d, failed: %d, skipped: %d",
        user_id[:8], len(created), failed, skipped,
    )
    return {"created": created, "failed": failed, "skipped": skipped}
