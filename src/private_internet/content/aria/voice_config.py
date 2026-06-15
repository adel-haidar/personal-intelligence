"""ARIA podcast host voice routing for ElevenLabs.

Two distinct hosts per episode (Host A measured/analytical, Host B
expressive/warm), each with its own voice id per language and its own voice
settings. With eleven_multilingual_v2 a single voice can speak any language,
but we keep per-language slots so native voices can be auditioned in later.

All IDs below are PLACEHOLDERS. They contain the literal substring "VOICE_ID_",
which `podcast_voices_configured()` uses to detect that real auditioned voices
have not been wired in yet. Placeholder IDs will fail against the real
ElevenLabs API, so the generator refuses to make TTS calls until they are set.
"""

import logging

logger = logging.getLogger(__name__)

# Podcast host voices — audition in ElevenLabs before going live.
# Host A: measured, analytical. Host B: expressive, warm.
# Use different voice IDs per host so they sound distinctly different.
PODCAST_VOICE_IDS: dict[str, dict[str, str]] = {
    "host_a": {
        "en": "VOICE_ID_HOST_A_ENGLISH",    # TODO: audition in ElevenLabs
        "de": "VOICE_ID_HOST_A_GERMAN",     # TODO: audition in ElevenLabs
        "ar": "VOICE_ID_HOST_A_ARABIC",     # TODO: audition in ElevenLabs
        "fr": "VOICE_ID_HOST_A_FRENCH",     # TODO: audition in ElevenLabs
        "ru": "VOICE_ID_HOST_A_RUSSIAN",    # TODO: audition in ElevenLabs
    },
    "host_b": {
        "en": "VOICE_ID_HOST_B_ENGLISH",    # TODO: audition in ElevenLabs
        "de": "VOICE_ID_HOST_B_GERMAN",     # TODO: audition in ElevenLabs
        "ar": "VOICE_ID_HOST_B_ARABIC",     # TODO: audition in ElevenLabs
        "fr": "VOICE_ID_HOST_B_FRENCH",     # TODO: audition in ElevenLabs
        "ru": "VOICE_ID_HOST_B_RUSSIAN",    # TODO: audition in ElevenLabs
    },
}

# Host A: more stable (measured delivery)
HOST_A_VOICE_SETTINGS = {"stability": 0.65, "similarity_boost": 0.75}
# Host B: less stable (more expressive and spontaneous)
HOST_B_VOICE_SETTINGS = {"stability": 0.45, "similarity_boost": 0.80}

# Default display names for the two hosts.
DEFAULT_HOST_A_NAME = "Alex"
DEFAULT_HOST_B_NAME = "Jordan"


def get_podcast_voice_id(host_key: str, language_code: str) -> str:
    """ElevenLabs voice id for a host in a language.

    Falls back to the host's English voice when the language is unmapped, and
    logs a warning when that fallback is triggered (per the spec). `host_key`
    must be 'host_a' or 'host_b'.
    """
    voices = PODCAST_VOICE_IDS[host_key]
    voice_id = voices.get(language_code)
    if voice_id is None:
        logger.warning(
            "No podcast voice for %s/%s — falling back to English voice",
            host_key, language_code,
        )
        return voices["en"]
    return voice_id


def voice_settings_for_host(host: str) -> dict:
    """Voice settings for a dialogue line's host ('A' or 'B')."""
    return HOST_A_VOICE_SETTINGS if host == "A" else HOST_B_VOICE_SETTINGS


def podcast_voices_configured() -> bool:
    """True only when every voice id is a real (non-placeholder) ElevenLabs id."""
    for voices in PODCAST_VOICE_IDS.values():
        for voice_id in voices.values():
            if "VOICE_ID_" in voice_id:
                return False
    return True


def warn_if_podcast_voices_unconfigured() -> None:
    """Startup check: log a clear warning if podcast voices are still placeholders."""
    if not podcast_voices_configured():
        logger.warning(
            "ARIA podcast voices are not configured — PODCAST_VOICE_IDS still "
            "contains placeholder values. Podcast generation will be skipped until "
            "real ElevenLabs voice IDs are set in content/aria/voice_config.py."
        )
