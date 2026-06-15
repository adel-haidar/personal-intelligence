"""fal.ai video generation (Kling) for SIGNAL section clips.

Replaces the legacy still-image + Ken-Burns slides with a real generated video
clip per section. Uses fal's async queue API: submit a job, poll until COMPLETE,
then download the resulting mp4 bytes. Video models produce short silent clips
(Kling v1 = 5/10s; others e.g. Veo3 also do 8s) and the assembler stitches them
under the narration.

Callers pass the per-scene requested duration in seconds; this module snaps it
to a value the configured model actually supports (`fal_video_durations`), so a
caller never has to know the model's clip-length menu. Callers keep a slide /
fallback-card, so an unfunded balance or any error degrades gracefully rather
than failing the whole video.
"""

import asyncio
import logging
from typing import List, Union

import httpx

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

_QUEUE = "https://queue.fal.run/"
_POLL_INTERVAL_S = 5
_MAX_POLLS = 120  # ~10 min ceiling per clip
_DEFAULT_DURATION_S = 5


def _supported_durations() -> List[int]:
    """Parse the configured model's supported clip durations (seconds)."""
    raw = get_settings().fal_video_durations or ""
    values = sorted({int(x) for x in raw.split(",") if x.strip().isdigit()})
    return values or [_DEFAULT_DURATION_S]


def _snap_duration(requested: int, supported: List[int]) -> int:
    """Snap a requested duration to the nearest supported value. Ties (a request
    exactly between two options, e.g. 8 vs {5,10} ⇒ closer to 10) resolve to the
    LONGER clip, so the visual never under-runs the scene's narration."""
    return min(supported, key=lambda d: (abs(d - requested), -d))


async def generate_video_clip(
    prompt: str,
    *,
    duration: Union[int, str] = _DEFAULT_DURATION_S,
    aspect_ratio: str = "16:9",
) -> bytes:
    """Generate one short video clip from a text prompt; return mp4 bytes.

    `duration` is the requested clip length in seconds (int or str). It is
    snapped to the configured model's supported menu before the API call, so
    passing 8 against Kling v1 yields a 10s clip, while a Veo3 deployment
    (fal_video_durations="5,8,10") would honour 8 exactly. Raises on failure.
    """
    s = get_settings()
    if not s.fal_api_key:
        raise RuntimeError("FAL_AI_API_KEY not configured")

    try:
        requested = int(duration)
    except (TypeError, ValueError):
        requested = _DEFAULT_DURATION_S
    supported = _supported_durations()
    snapped = _snap_duration(requested, supported)
    if snapped != requested:
        logger.debug(
            "fal video: requested %ss not supported by %s; snapped to %ss (supported=%s)",
            requested, s.fal_video_model, snapped, supported,
        )

    model = s.fal_video_model
    headers = {"Authorization": f"Key {s.fal_api_key}", "Content-Type": "application/json"}
    body = {"prompt": prompt, "duration": str(snapped), "aspect_ratio": aspect_ratio}

    async with httpx.AsyncClient(timeout=120) as client:
        # 1. Submit to the queue.
        sub = await client.post(f"{_QUEUE}{model}", json=body, headers=headers)
        sub.raise_for_status()
        job = sub.json()
        req_id = job["request_id"]
        status_url = job.get("status_url") or f"{_QUEUE}{model}/requests/{req_id}/status"
        response_url = job.get("response_url") or f"{_QUEUE}{model}/requests/{req_id}"

        # 2. Poll until done.
        for _ in range(_MAX_POLLS):
            await asyncio.sleep(_POLL_INTERVAL_S)
            st = await client.get(status_url, headers=headers)
            st.raise_for_status()
            status = st.json().get("status")
            if status == "COMPLETED":
                break
            if status in ("FAILED", "ERROR"):
                raise RuntimeError(f"fal video job failed: {str(st.json())[:200]}")
        else:
            raise RuntimeError("fal video job timed out")

        # 3. Fetch result + download the mp4.
        res = await client.get(response_url, headers=headers)
        res.raise_for_status()
        url = (res.json().get("video") or {}).get("url")
        if not url:
            raise RuntimeError(f"fal video: no url in result {str(res.json())[:200]}")
        vid = await client.get(url)
        vid.raise_for_status()
        return vid.content
