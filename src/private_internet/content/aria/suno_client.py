"""Suno AI client for ARIA music generation.

Generates full-length music tracks (2–4 minutes) from a text prompt via the
Suno API at https://api.sunoapi.org. Replaces the ElevenLabs music path for
ARIA only — SIGNAL / STORIES / podcast narration are untouched.

All endpoint paths and field names verified against the sunoapi.org docs:
  - Generate:  POST {base}/api/v1/generate
      body: customMode, instrumental, model, style, title, prompt?, callBackUrl
      → {"code":200,"msg":"success","data":{"taskId": "..."}}
  - Status:    GET  {base}/api/v1/generate/record-info?taskId=...
      → data.status ∈ {PENDING, TEXT_SUCCESS, FIRST_SUCCESS, SUCCESS,
                        CREATE_TASK_FAILED, GENERATE_AUDIO_FAILED,
                        CALLBACK_EXCEPTION, SENSITIVE_WORD_ERROR}
        audio at data.response.sunoData[].audioUrl

Suno requires a callBackUrl on every request; we do NOT consume callbacks —
polling record-info is authoritative. The client is async but performs the
blocking urllib HTTP in a thread executor so it never stalls the event loop.
No third-party HTTP dependency (httpx) is required.
"""

import asyncio
import io
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

# sunoapi.org sits behind Cloudflare, which rejects the default
# `Python-urllib/x.y` agent with HTTP 403 "error code: 1010" (browser-signature
# ban). Send a normal browser UA on every request so the calls are accepted.
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

POLL_INTERVAL_SECONDS = 10
MAX_POLL_ATTEMPTS = 60  # 10 minutes maximum wait per track

# Duration policy (seconds): hard-reject below MIN; target ~180; we do not
# reject long tracks (Suno tops out around 4 min anyway).
MIN_DURATION_SECONDS = 120
TARGET_DURATION_SECONDS = 180

# data.status values that mean the job is permanently dead.
_FAILED_STATES = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION",
    "SENSITIVE_WORD_ERROR",
}
_SUCCESS_STATE = "SUCCESS"


class SunoGenerationError(Exception):
    """Raised on submit failure, job failure, timeout, or too-short audio."""


@dataclass
class SunoResult:
    audio: bytes
    task_id: str
    duration_seconds: float = 0.0


def get_audio_duration_seconds(mp3_bytes: bytes) -> float:
    """Measure MP3 duration in seconds via pydub (already a project dep)."""
    from pydub import AudioSegment

    audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
    return len(audio) / 1000.0


class SunoClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        callback_url: Optional[str] = None,
    ):
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.suno_api_key
        self.base_url = (base_url or s.suno_base_url).rstrip("/")
        self.model = model or s.suno_model
        # callBackUrl is required by the API even though we poll. Fall back to a
        # path on our own domain; we never serve a receiver there.
        self.callback_url = (
            callback_url or s.suno_callback_url or f"{s.base_url}/api/aria/suno/callback"
        )

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_track(
        self,
        *,
        prompt: str,
        style: str,
        title: str,
        instrumental: bool = True,
        duration_seconds: int = TARGET_DURATION_SECONDS,
    ) -> SunoResult:
        """Submit one generation job, poll until complete, return MP3 bytes.

        `duration_seconds` is advisory only — Suno has no duration parameter, so
        it is accepted for interface parity and ignored in the request body.
        Raises SunoGenerationError on submit failure, job failure, or timeout.
        """
        task_id = await self._submit(
            prompt=prompt, style=style, title=title, instrumental=instrumental
        )
        audio = await self._poll_until_complete(task_id)
        return SunoResult(audio=audio, task_id=task_id)

    async def generate_with_min_duration(
        self,
        *,
        prompt: str,
        style: str,
        title: str,
        instrumental: bool = True,
        min_seconds: int = MIN_DURATION_SECONDS,
    ) -> SunoResult:
        """Generate a track, enforce the minimum duration, retry once on short.

        On a too-short track, retries once with ', extended version, full length'
        appended to the style prompt. If the retry is also too short, raises
        SunoGenerationError (the caller marks the track failed — never saved).
        """
        result = await self.generate_track(
            prompt=prompt, style=style, title=title, instrumental=instrumental
        )
        duration = await self._duration(result.audio)
        if duration >= min_seconds:
            result.duration_seconds = duration
            return result

        logger.warning(
            "Suno track too short (%.0fs, job %s) — retrying with extended style",
            duration,
            result.task_id,
        )
        ext_style = f"{style}, extended version, full length"
        retry = await self.generate_track(
            prompt=prompt, style=ext_style, title=title, instrumental=instrumental
        )
        retry_duration = await self._duration(retry.audio)
        if retry_duration < min_seconds:
            raise SunoGenerationError(
                f"Track too short after retry: {retry_duration:.0f}s "
                f"(min {min_seconds}s, job {retry.task_id}, style '{ext_style}')"
            )
        retry.duration_seconds = retry_duration
        return retry

    # ── Polling ───────────────────────────────────────────────────────────────

    async def _poll_until_complete(self, task_id: str) -> bytes:
        for _ in range(MAX_POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            data = await self._fetch_record_info(task_id)
            status = (data or {}).get("status")
            if status == _SUCCESS_STATE:
                audio_url = _extract_audio_url(data)
                if not audio_url:
                    raise SunoGenerationError(
                        f"Suno job {task_id} reported SUCCESS but no audioUrl"
                    )
                return await self._download_audio(audio_url)
            if status in _FAILED_STATES:
                raise SunoGenerationError(f"Suno job {task_id} failed: {status}")
            # PENDING / TEXT_SUCCESS / FIRST_SUCCESS → keep polling.
        raise SunoGenerationError(
            f"Suno job {task_id} timed out after "
            f"{MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s"
        )

    # ── HTTP leaves (mock points for tests) ──────────────────────────────────

    async def _submit(
        self, *, prompt: str, style: str, title: str, instrumental: bool
    ) -> str:
        payload = {
            "customMode": True,
            "instrumental": instrumental,
            "model": self.model,
            "style": style[:1000],
            "title": title[:100],
            "callBackUrl": self.callback_url,
        }
        # In custom mode with vocals, `prompt` carries the exact lyrics. For an
        # instrumental track it is omitted (Suno rejects lyrics + instrumental).
        if not instrumental and prompt:
            payload["prompt"] = prompt

        resp = await self._post("/api/v1/generate", payload)
        if resp.get("code") != 200:
            raise SunoGenerationError(
                f"Suno generate rejected: code={resp.get('code')} msg={resp.get('msg')}"
            )
        task_id = (resp.get("data") or {}).get("taskId")
        if not task_id:
            raise SunoGenerationError("Suno generate returned no taskId")
        return task_id

    async def _fetch_record_info(self, task_id: str) -> dict:
        resp = await self._get(f"/api/v1/generate/record-info?taskId={task_id}")
        return resp.get("data") or {}

    async def _download_audio(self, audio_url: str) -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _http_get_bytes(audio_url))

    async def _duration(self, mp3_bytes: bytes) -> float:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: get_audio_duration_seconds(mp3_bytes)
        )

    # ── urllib transport (offloaded to a thread) ─────────────────────────────

    async def _post(self, path: str, payload: dict) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _http_json(self.base_url + path, self.headers, payload)
        )

    async def _get(self, path: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _http_json(self.base_url + path, self.headers, None)
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


def _extract_audio_url(data: dict) -> Optional[str]:
    """data.response.sunoData[0].audioUrl, defensively."""
    suno_data = ((data or {}).get("response") or {}).get("sunoData") or []
    for item in suno_data:
        url = item.get("audioUrl") or item.get("streamAudioUrl")
        if url:
            return url
    return None


def _http_json(url: str, headers: dict, payload: Optional[dict]) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace") if hasattr(e, "read") else ""
        raise SunoGenerationError(f"Suno API HTTP {e.code} for {url}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise SunoGenerationError(f"Suno API unreachable ({url}): {e.reason}") from e


def _http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise SunoGenerationError(f"Suno audio download HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise SunoGenerationError(f"Suno audio unreachable ({url}): {e.reason}") from e
