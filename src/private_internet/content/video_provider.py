"""Video generation provider routing — the single source of truth.

Video clips are split across two providers by content type:

  - Wan2.1 (Replicate)  → SIGNAL + PULSE  — high volume, cost-efficient
  - Kling (fal.ai)      → STORIES         — cinematic, long-form

The mapping below is the ONLY place that decides which provider a content type
uses. No other module contains routing logic. If the rule changes, it changes
here and nowhere else.
"""

import logging

logger = logging.getLogger(__name__)


VIDEO_PROVIDER_MAP: dict[str, str] = {
    "stories": "kling",   # heavy lifting — cinematic, long-form
    "signal":  "wan2",    # high volume — cost-efficient
    "pulse":   "wan2",    # visual content — cost-efficient
}


def get_provider(content_type: str) -> str:
    """
    Returns the video generation provider for a given content type.
    Deterministic. No LLM. No dynamic logic.
    content_type: 'stories' | 'signal' | 'pulse'
    """
    provider = VIDEO_PROVIDER_MAP.get(content_type)
    if provider is None:
        raise ValueError(
            f"Unknown content_type '{content_type}'. "
            f"Must be one of: {list(VIDEO_PROVIDER_MAP.keys())}"
        )
    return provider


# Estimated per-clip cost in EUR. Not used for billing — only for the internal
# cost log so monthly generation spend can be queried per provider/content type.
# Update as Replicate / Kling pricing changes.
ESTIMATED_COST_EUR = {
    "wan2":  0.20,   # per clip — Wan2.1 on Replicate
    "kling": 1.50,   # per clip — Kling (fal.ai) Standard tier
}


def log_generation_cost(
    provider: str,
    content_type: str,
    scene_number: int,
    is_fallback: bool,
) -> None:
    """
    Logs estimated cost per clip for monitoring.
    Not used for billing — only for internal cost tracking.
    """
    cost = ESTIMATED_COST_EUR.get(provider, 0.0)
    logger.info(
        "video_clip_generated",
        extra={
            "provider": provider,
            "content_type": content_type,
            "scene_number": scene_number,
            "is_fallback": is_fallback,
            "estimated_cost_eur": cost,
        },
    )
