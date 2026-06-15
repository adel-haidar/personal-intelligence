"""ARIA podcast module unit tests — no network, no DB.

Covers (per the PROMPT 5 spec):
- Silence file generation produces files of the correct duration.
- Concat manifest interleaves lines and silences in the right order.
- Dialogue audio is generated in order, host A then host B as scripted.
- Language code falls back to English when unmapped.
- Voice settings are applied correctly per host.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from private_internet.content.aria import podcast_generator as pg
from private_internet.content.aria.voice_config import (
    HOST_A_VOICE_SETTINGS,
    HOST_B_VOICE_SETTINGS,
    get_podcast_voice_id,
    podcast_voices_configured,
    voice_settings_for_host,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True,
    )
    return float(out.stdout.strip())


# ── Silence file generation ────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
class TestSilenceGeneration:
    def test_all_pause_durations_created(self, tmp_path):
        paths = pg._generate_silence_files(tmp_path)
        assert set(paths.keys()) == set(pg.PAUSE_DURATIONS_MS)
        for ms, p in paths.items():
            assert p.exists()

    def test_silence_durations_match(self, tmp_path):
        paths = pg._generate_silence_files(tmp_path)
        for ms, p in paths.items():
            measured = _probe_duration(p)
            expected = ms / 1000.0
            # mp3 framing rounds slightly; allow 60ms slack.
            assert abs(measured - expected) < 0.06, f"{ms}ms -> {measured}s"


# ── Concat manifest format ─────────────────────────────────────────────────────

class TestConcatManifest:
    def test_interleaves_lines_and_silences(self):
        dialogue_audio = [(b"a", 400), (b"b", 600), (b"c", 100)]
        line_paths = [Path("/tmp/line_0000.mp3"),
                      Path("/tmp/line_0001.mp3"),
                      Path("/tmp/line_0002.mp3")]
        tmp_dir = Path("/tmp")
        manifest = pg._build_concat_manifest(dialogue_audio, line_paths, tmp_dir)
        lines = manifest.strip().split("\n")
        assert lines == [
            "file '/tmp/line_0000.mp3'",
            "file '/tmp/silence_400ms.mp3'",
            "file '/tmp/line_0001.mp3'",
            "file '/tmp/silence_600ms.mp3'",
            "file '/tmp/line_0002.mp3'",
            "file '/tmp/silence_100ms.mp3'",
        ]

    def test_one_silence_per_line(self):
        dialogue_audio = [(b"x", 1200)] * 5
        line_paths = [Path(f"/tmp/line_{i:04d}.mp3") for i in range(5)]
        manifest = pg._build_concat_manifest(dialogue_audio, line_paths, Path("/tmp"))
        rows = manifest.strip().split("\n")
        # 5 lines + 5 silences = 10 rows.
        assert len(rows) == 10
        assert sum(1 for r in rows if "silence_1200ms" in r) == 5


# ── Dialogue audio ordering + voice settings ────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


class TestDialogueAudio:
    def _dialogue(self):
        return [
            {"host": "A", "text": "Line one from A.", "pause_after_ms": 600},
            {"host": "B", "text": "Line two from B.", "pause_after_ms": 100},
            {"host": "A", "text": "Line three from A.", "pause_after_ms": 400},
        ]

    def test_ordering_and_pauses_preserved(self):
        def fake(text, voice_id, *, stability, similarity_boost, model_id):
            return f"audio:{text}".encode()

        with patch.object(pg, "_synthesize_line", side_effect=fake), \
             patch("asyncio.sleep", new=AsyncMock()):
            result = _run(pg.generate_dialogue_audio(self._dialogue(), "en"))

        assert [r[0] for r in result] == [
            b"audio:Line one from A.",
            b"audio:Line two from B.",
            b"audio:Line three from A.",
        ]
        assert [r[1] for r in result] == [600, 100, 400]

    def test_voice_settings_applied_per_host(self):
        calls = []

        def fake(text, voice_id, *, stability, similarity_boost, model_id):
            calls.append({"stability": stability, "similarity_boost": similarity_boost})
            return b"x"

        with patch.object(pg, "_synthesize_line", side_effect=fake), \
             patch("asyncio.sleep", new=AsyncMock()):
            _run(pg.generate_dialogue_audio(self._dialogue(), "en"))

        # A, B, A
        assert calls[0] == HOST_A_VOICE_SETTINGS
        assert calls[1] == HOST_B_VOICE_SETTINGS
        assert calls[2] == HOST_A_VOICE_SETTINGS

    def test_invalid_pause_normalized_to_400(self):
        dialogue = [{"host": "A", "text": "hi", "pause_after_ms": 999}]
        with patch.object(pg, "_synthesize_line", return_value=b"x"), \
             patch("asyncio.sleep", new=AsyncMock()):
            result = _run(pg.generate_dialogue_audio(dialogue, "en"))
        assert result[0][1] == 400

    def test_distinct_voices_per_host(self):
        seen = []

        def fake(text, voice_id, *, stability, similarity_boost, model_id):
            seen.append(voice_id)
            return b"x"

        with patch.object(pg, "_synthesize_line", side_effect=fake), \
             patch("asyncio.sleep", new=AsyncMock()):
            _run(pg.generate_dialogue_audio(self._dialogue(), "en"))

        # Host A's voice (calls 0,2) differs from Host B's (call 1).
        assert seen[0] == seen[2]
        assert seen[0] != seen[1]


# ── Voice config: language fallback + settings ─────────────────────────────────

class TestVoiceConfig:
    def test_settings_for_host(self):
        assert voice_settings_for_host("A") == HOST_A_VOICE_SETTINGS
        assert voice_settings_for_host("B") == HOST_B_VOICE_SETTINGS

    def test_known_language_returns_its_voice(self):
        assert get_podcast_voice_id("host_a", "de") != get_podcast_voice_id("host_a", "en")

    def test_unmapped_language_falls_back_to_english(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            voice = get_podcast_voice_id("host_a", "jp")  # not in the map
        assert voice == get_podcast_voice_id("host_a", "en")
        assert any("falling back to English" in r.message for r in caplog.records)

    def test_placeholder_voices_detected_as_unconfigured(self):
        # The shipped config is all placeholders, so this must be False until
        # real ElevenLabs IDs are wired in.
        assert podcast_voices_configured() is False
