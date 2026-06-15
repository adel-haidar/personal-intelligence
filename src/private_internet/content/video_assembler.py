"""
Shared video assembly pipeline for SIGNAL and STORIES.

No video model (Kling, Veo3, …) generates more than ~2 minutes of coherent
video per call, but STORIES needs 6–45 minutes and SIGNAL needs 3–5. This
module stitches many short clips into one long video:

    translate visuals → generate N clips (parallel, semaphored)
                      → narration (ElevenLabs/Polly)
                      → FFmpeg concat + mux → upload to S3

Used by both SIGNAL and STORIES — the scene-stitching logic lives here once.
"""

import asyncio
import inspect
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Union

from private_internet.content.asset_store import AssetStore
from private_internet.content.elevenlabs_engine import ElevenLabsEngine, get_tts_engine
from private_internet.content.fal_video import generate_video_clip
from private_internet.content.visual_translator import (
    build_final_prompt,
    kling_duration,
    translate_scenes,
)
from private_internet.content.voice_config import get_voice_id

logger = logging.getLogger(__name__)

MAX_CONCURRENT_KLING_CALLS = 4  # semaphore limit — never exceed (Kling rate limits)

# Mood → fallback solid-colour card (used when a clip fails to generate). The
# keys match the visual translator's mood enum. Dark, Calm-Intelligence tints so
# a failed scene degrades quietly.
MOOD_FALLBACK_COLORS = {
    "calm":        "#1A1A28",
    "tense":       "#1A0C0C",
    "warm":        "#1A130C",
    "melancholic": "#0C0C1A",
    "energetic":   "#0C1A0C",
}

# Script scenes carry a scene_type, not a mood — map one to the other for the
# fallback colour when the visual translator did not supply a mood.
_SCENE_TYPE_MOOD = {
    "establishing": "calm",
    "development":  "warm",
    "transition":   "melancholic",
    "climax":       "tense",
    "resolution":   "calm",
}

# Camera/lighting language appended per scene_type when the LLM visual translator
# is unavailable (deterministic + pure-Python so assembly still proceeds without
# sending abstract topic text to Kling).
_SCENE_TYPE_STYLE = {
    "establishing": "wide establishing shot, slow push-in",
    "development":  "medium shot, gentle camera movement",
    "transition":   "sweeping transition, motion blur",
    "climax":       "dramatic close-up, dynamic motion",
    "resolution":   "calm pull-back, settling motion",
}

_FALLBACK_DURATION_DEFAULT = 8
_SEGMENT_SCENE_LIMIT = 50  # STORIES episodes > ~15 min are generated in segments


ProgressCb = Optional[Callable[[dict], Union[None, Awaitable[None]]]]


def _scene_mood(scene: dict) -> str:
    return _SCENE_TYPE_MOOD.get(scene.get("scene_type"), "calm")


def translate_visuals_batch(scenes: List[dict]) -> List[str]:
    """Deterministic fallback translator: turn each scene's visual_description
    into a Kling prompt with cinematic/camera language keyed by scene_type.

    Used only when the LLM visual translator (Prompt 2) returns nothing, so the
    pipeline never sends raw abstract topic text to Kling. Order preserved.
    """
    prompts = []
    for scene in scenes:
        desc = (scene.get("visual_description") or "").strip().rstrip(".")
        style = _SCENE_TYPE_STYLE.get(scene.get("scene_type"), "cinematic shot")
        prompts.append(
            f"{desc}. {style}, cinematic, dark editorial style, "
            "photorealistic, 16:9, no text, no watermark"
        )
    return prompts


def chunk_scenes(scenes: List[dict], size: int = _SEGMENT_SCENE_LIMIT) -> List[List[dict]]:
    """Split scenes into segments (default 50) for memory-bounded assembly of
    long STORIES episodes. Each segment can be assembled then concatenated."""
    return [scenes[i:i + size] for i in range(0, len(scenes), size)] or [[]]


def _check_ffmpeg() -> None:
    """Fail fast with a clear message if FFmpeg is not installed."""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    except FileNotFoundError:
        result = None
    if result is None or result.returncode != 0:
        raise RuntimeError("FFmpeg not found. Run: sudo apt-get install -y ffmpeg")


def _run_ffmpeg(args: List[str]) -> None:
    result = subprocess.run(args, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        logger.error("FFmpeg failed: %s\n%s", " ".join(args), stderr[-2000:])
        raise RuntimeError(f"FFmpeg command failed: {stderr[-1000:]}")


def fallback_card_command(hex_color: str, duration: int, out_path: str) -> List[str]:
    """FFmpeg argv for a solid-colour 1920x1080 card of `duration` seconds."""
    return [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={hex_color}:size=1920x1080:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_path),
    ]


def generate_fallback_card(mood: str, duration: int, out_path: str) -> None:
    """Render a mood-coloured fallback card for a scene whose clip failed."""
    hex_color = MOOD_FALLBACK_COLORS.get(mood, MOOD_FALLBACK_COLORS["calm"])
    logger.warning("Using %s fallback card (%s) → %s", mood, hex_color, out_path)
    _run_ffmpeg(fallback_card_command(hex_color, duration, str(out_path)))


def write_concat_manifest(clip_paths: List[str], manifest_path: str) -> str:
    """Write the FFmpeg concat-demuxer manifest (`file '<path>'` per line)."""
    with open(manifest_path, "w") as f:
        for clip_path in clip_paths:
            f.write(f"file '{clip_path}'\n")
    return manifest_path


async def _emit(on_progress: ProgressCb, patch: dict) -> None:
    """Invoke a sync or async progress callback, swallowing its errors so a
    progress-write failure never aborts the assembly."""
    if on_progress is None:
        return
    try:
        result = on_progress(patch)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # progress is best-effort
        logger.warning("progress callback failed (ignored): %s", exc)


def _synthesize_narration(narration_text: str, language_code: str, out_path: str) -> None:
    """Generate the full narration mp3 via the configured TTS engine."""
    tts = get_tts_engine()
    # ElevenLabs is multilingual (voice per language); Polly needs a real voice id.
    voice_id = get_voice_id(language_code) if isinstance(tts, ElevenLabsEngine) else "Joanna"
    tts.synthesize_section(narration_text, voice_id, language_code, out_path)


def _build_clip_plan(script_scenes: List[dict], translated: List[dict]) -> List[dict]:
    """Pair each script scene with its translated Kling prompt, clip duration and
    mood. Falls back to a deterministic prompt/mood for any scene the LLM
    translator did not cover, so every scene yields a clip plan entry."""
    fallback_prompts = translate_visuals_batch(script_scenes)
    plan = []
    for i, scene in enumerate(script_scenes):
        t = translated[i] if i < len(translated) else None
        card_duration = int(scene.get("duration_seconds") or _FALLBACK_DURATION_DEFAULT)
        if t:
            prompt = build_final_prompt(t)
            clip_duration = kling_duration(t)          # "5" | "10"
            mood = t.get("mood") or _scene_mood(scene)
        else:
            prompt = fallback_prompts[i]
            clip_duration = "10" if card_duration >= 8 else "5"
            mood = _scene_mood(scene)
        plan.append({
            "scene_number": scene.get("scene_number", i + 1),
            "kling_prompt": prompt,
            "clip_duration": clip_duration,
            "card_duration": card_duration,
            "mood": mood,
        })
    return plan


async def assemble_video(
    scenes: List[dict],          # from the script tool output
    narration_text: str,         # full narration for ElevenLabs
    language_code: str,          # for voice routing
    output_s3_key: str,          # where to upload the final MP4
    content_type: str,           # 'signal' or 'stories'
    *,
    topic_name: str = "",        # passed to the visual translator
    on_progress: ProgressCb = None,
) -> str:
    """
    Full pipeline: translate → generate clips → narration → stitch → upload.
    Returns the S3 key of the assembled video.

    Resilience guarantees:
    - A clip that fails to generate is replaced by a mood-coloured fallback card.
      The whole assembly is NEVER aborted for one failed clip.
    - Temp files are cleaned up only on success. On failure (e.g. S3 upload) the
      temp directory is kept and its path logged for debugging.
    - `on_progress(patch: dict)` is called after every clip (not batched) and at
      each stage boundary; it may be sync or async.
    """
    _check_ffmpeg()

    work_dir = Path(tempfile.mkdtemp(prefix=f"{content_type}_assembly_"))
    total = len(scenes)
    succeeded = False
    try:
        # Step 1 — translate all scenes to concrete Kling prompts (Prompt 2).
        target_duration = sum(
            int(s.get("duration_seconds") or _FALLBACK_DURATION_DEFAULT) for s in scenes
        )
        translated = await translate_scenes(
            topic=topic_name,
            narration_script=narration_text,
            total_scenes=total,
            target_duration_seconds=target_duration,
        )
        plan = _build_clip_plan(scenes, translated)

        await _emit(on_progress, {
            "total_scenes": total,
            "clips_generated": 0,
            "narration_ready": False,
            "assembly_started": False,
            "current_stage": "generating_clips",
        })

        # Step 2 — generate clips in parallel, capped by the semaphore.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_KLING_CALLS)
        done_lock = asyncio.Lock()
        clips_done = 0

        async def generate_one_clip(entry: dict) -> str:
            nonlocal clips_done
            scene_number = entry["scene_number"]
            clip_path = work_dir / f"clip_{scene_number:04d}.mp4"
            async with semaphore:
                try:
                    data = await generate_video_clip(
                        entry["kling_prompt"],
                        duration=entry["clip_duration"],
                        aspect_ratio="16:9",
                    )
                    clip_path.write_bytes(data)
                except Exception as exc:
                    # Never abort the assembly for one failed clip.
                    logger.warning(
                        "clip generation failed (scene %s): %s", scene_number, exc
                    )
                    generate_fallback_card(entry["mood"], entry["card_duration"], str(clip_path))
            # Update progress after EVERY clip (not batched).
            async with done_lock:
                clips_done += 1
                current = clips_done
            await _emit(on_progress, {"clips_generated": current})
            return str(clip_path)

        clip_paths = await asyncio.gather(*(generate_one_clip(e) for e in plan))

        # Step 3 — narration audio (one ElevenLabs call for the full text).
        await _emit(on_progress, {"current_stage": "narration"})
        narration_path = work_dir / "narration.mp3"
        await asyncio.get_event_loop().run_in_executor(
            None, _synthesize_narration, narration_text, language_code, str(narration_path)
        )
        await _emit(on_progress, {
            "narration_ready": True,
            "assembly_started": True,
            "current_stage": "assembling",
        })

        # Step 4 — FFmpeg: concat all clips, then mux narration under the video.
        concat_path = work_dir / "concat.txt"
        write_concat_manifest(clip_paths, str(concat_path))

        video_only = work_dir / "video_only.mp4"
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_path),
            "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            str(video_only),
        ])

        final_path = work_dir / "final.mp4"
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(video_only),
            "-i", str(narration_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            str(final_path),
        ])

        # Step 5 — upload and (only then) clean up.
        await _emit(on_progress, {"current_stage": "uploading"})
        store = AssetStore()
        with open(final_path, "rb") as f:
            store._upload(output_s3_key, f, "video/mp4")

        succeeded = True
        await _emit(on_progress, {"current_stage": "complete"})
        logger.info(
            "[%s] assembled %d scenes → s3://%s", content_type, total, output_s3_key
        )
        return output_s3_key

    finally:
        if succeeded:
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            # Keep temp files on failure — they are needed for debugging.
            logger.error(
                "[%s] assembly failed — keeping temp files for debug at %s",
                content_type, work_dir,
            )
