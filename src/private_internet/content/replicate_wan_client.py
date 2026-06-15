"""Replicate client for Wan2.1 video generation.

Used for SIGNAL and PULSE content — high volume, cost-efficient. Wan2.1 is
Alibaba's open-source video-generation model, available on Replicate at a
fraction of Kling's API pricing. STORIES stays on Kling (see video_provider.py).

Mirrors the resilience contract of the fal/Kling client (content/fal_video.py):
submit a job, poll until it finishes, then download the resulting mp4 bytes.
Callers keep a colour-card fallback, so an error or timeout degrades gracefully
rather than failing the whole video. A failed SIGNAL/PULSE clip must NEVER fall
through to Kling — that constraint lives in the assembler and protects the cost
model.

The `replicate` SDK is imported lazily (inside the client) so this module — and
the assembler that imports it at module load — never fails to import when the
package or REPLICATE_API_KEY is absent. The error surfaces only when a clip is
actually requested, exactly like the fal client's missing-key behaviour.
"""

import asyncio
import logging

import httpx

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

# Verified Replicate model slug. wan-video/wan-2.1-1.3b is Alibaba Tongyi Lab's
# open Wan2.1 1.3B text-to-video model — it emits ~5s 480p clips. Confirmed live
# on https://replicate.com/wan-video/wan-2.1-1.3b (2026-06). Overridable per
# instance via WAN2_MODEL for a higher-res / duration-configurable Wan variant
# (e.g. wavespeedai/wan-2.1-t2v-480p). Passing `model=` without a `:version`
# resolves the model's latest version on Replicate.
_DEFAULT_WAN2_MODEL = "wan-video/wan-2.1-1.3b"

POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 120   # 10 minutes max (Wan2.1 is faster than Kling)


class Wan2GenerationError(Exception):
    pass


class ReplicateWanClient:
    """
    Generates video clips via Wan2.1 on Replicate.
    Returns raw MP4 bytes per clip.

    The configured model (wan-video/wan-2.1-1.3b) produces fixed ~5s 480p clips,
    so the duration/width/height arguments are advisory and accepted for
    forward-compatibility with a duration-configurable Wan variant. They are NOT
    forwarded as input fields today — Replicate rejects unknown input keys, and
    the 1.3B model exposes no such fields. See the TODO in generate_clip().
    """

    def __init__(self):
        # Lazy: the replicate.Client is only built on first use, so importing
        # this module never requires the `replicate` package or an API key.
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import replicate  # imported lazily — see module docstring
            except ImportError as e:  # pragma: no cover - depends on install env
                raise Wan2GenerationError(
                    "The 'replicate' package is not installed. "
                    "Run: pip install replicate"
                ) from e
            api_token = get_settings().replicate_api_key
            if not api_token:
                raise Wan2GenerationError("REPLICATE_API_KEY not configured")
            self._client = replicate.Client(api_token=api_token)
        return self._client

    @staticmethod
    def _model() -> str:
        return get_settings().wan2_model or _DEFAULT_WAN2_MODEL

    async def generate_clip(
        self,
        prompt: str,
        duration_seconds: int = 5,
        width: int = 1280,
        height: int = 720,
    ) -> bytes:
        """
        Submits a generation to Replicate, polls until complete,
        returns raw MP4 bytes.
        Raises Wan2GenerationError on failure or timeout.
        """
        client = self._get_client()

        # Only `prompt` is forwarded. It is the one input field verified across
        # the Wan2.1 text-to-video models on Replicate; wan-2.1-1.3b emits a
        # fixed ~5s 480p clip and accepts no duration/aspect_ratio field.
        # TODO: when switching to a duration-configurable Wan variant
        # (e.g. wavespeedai/wan-2.1-t2v-480p), map duration_seconds / width /
        # height to that model's VERIFIED input fields (frames, fps,
        # aspect_ratio, …) before forwarding them — do not guess field names, a
        # bad key makes Replicate reject the prediction with HTTP 422.
        input_params = {
            "prompt": prompt,
        }

        try:
            prediction = await asyncio.to_thread(
                client.predictions.create,
                model=self._model(),
                input=input_params,
            )
        except Exception as e:
            raise Wan2GenerationError(f"Replicate submission failed: {e}")

        return await self._poll_until_complete(prediction.id)

    async def _poll_until_complete(self, prediction_id: str) -> bytes:
        client = self._get_client()
        for _attempt in range(MAX_POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

            try:
                prediction = await asyncio.to_thread(
                    client.predictions.get,
                    prediction_id,
                )
            except Exception as e:
                raise Wan2GenerationError(f"Replicate poll failed: {e}")

            if prediction.status == "succeeded":
                output = prediction.output
                # Wan2.1 returns a single video URL; some Replicate models wrap
                # it in a list. Handle both.
                if isinstance(output, list):
                    if not output:
                        raise Wan2GenerationError(
                            f"Wan2.1 prediction {prediction_id} returned no output"
                        )
                    output = output[0]
                if not output:
                    raise Wan2GenerationError(
                        f"Wan2.1 prediction {prediction_id} returned no output"
                    )
                return await self._download_clip(str(output))

            elif prediction.status in ("failed", "canceled"):
                raise Wan2GenerationError(
                    f"Wan2.1 prediction {prediction_id} {prediction.status}: "
                    f"{prediction.error}"
                )
            # status is 'starting' or 'processing' — keep polling

        raise Wan2GenerationError(
            f"Wan2.1 prediction {prediction_id} timed out after "
            f"{MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s"
        )

    async def _download_clip(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
