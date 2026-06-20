"""Tests for the SIGNAL visual scene translation layer.

Core guarantees under test:
  - KLING_STYLE_SUFFIX is ALWAYS appended to the final Kling prompt.
  - The original abstract topic text NEVER reaches the Kling prompt — only the
    translated, concrete scene description does.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from private_internet.content.visual_translator import (
    KLING_STYLE_SUFFIX,
    VISUAL_TRANSLATOR_TOOL,
    build_final_prompt,
    kling_duration,
    translate_scenes,
)
from private_internet.content.jobs.video_job import (
    _section_visual,
    _translate_scenes_for_script,
)
from private_internet.content.video_generator import VideoScript, ScriptSection, SECTION_IDS

# The abstract topic the script generator produces — a terrible Kling prompt.
ABSTRACT_TOPIC = "A philosophical reflection on the circular economy"

# What a good cinematographer translates it into — concrete + filmable.
CONCRETE_PROMPTS = [
    "A man in his 30s picks up a broken lamp at a Berlin flea market, turns it "
    "over, sets it down carefully. Sunday morning, warm light. Slow push-in.",
    "A woman sorts glass bottles into wooden crates in a sunlit workshop. "
    "Dust drifts. Handheld, slight movement.",
    "Close on weathered hands repairing a bicycle wheel in a garage. "
    "Practical lighting. Static shot.",
    "Rain on a workshop window at dusk, tools blurred behind it. Slow pull-back.",
    "An empty repair shop at closing time, single warm bulb overhead. "
    "Low angle, static.",
]


def _scene(n: int, prompt: str, duration: int = 5, mood: str = "calm") -> dict:
    return {
        "scene_number": n,
        "kling_prompt": prompt,
        "duration_seconds": duration,
        "mood": mood,
    }


def _scene_descriptions() -> dict:
    return {
        "scene_descriptions": [
            _scene(i + 1, p) for i, p in enumerate(CONCRETE_PROMPTS)
        ]
    }


def _script() -> VideoScript:
    return VideoScript(
        title="The Quiet Repair",
        description="A look at the circular economy.",
        sections=[
            ScriptSection(id=sid, text=f"Narration for {sid}.", image_prompt=f"Abstract idea for {sid}")
            for sid in SECTION_IDS
        ],
    )


# ── build_final_prompt ─────────────────────────────────────────────

class TestBuildFinalPrompt:
    def test_always_appends_style_suffix(self):
        for scene in _scene_descriptions()["scene_descriptions"]:
            final = build_final_prompt(scene)
            assert final.endswith(KLING_STYLE_SUFFIX)
            assert scene["kling_prompt"] in final

    def test_original_topic_text_never_in_final_prompt(self):
        for scene in _scene_descriptions()["scene_descriptions"]:
            final = build_final_prompt(scene)
            assert ABSTRACT_TOPIC not in final
            assert "philosophical" not in final.lower()


class TestKlingDuration:
    @pytest.mark.parametrize("seconds,expected", [(5, 5), (8, 8), (10, 10), (None, 5), (0, 5)])
    def test_returns_requested_seconds_for_fal_to_snap(self, seconds, expected):
        # kling_duration only expresses intent; the fal call snaps to the model's
        # supported menu, so it must pass the requested value through unchanged.
        assert kling_duration({"duration_seconds": seconds}) == expected


# ── translate_scenes (Bedrock call mocked) ─────────────────────────

class TestTranslateScenes:
    @pytest.mark.anyio
    async def test_returns_concrete_scenes_without_topic_text(self):
        mock = AsyncMock(return_value=(_scene_descriptions(), {}))
        with patch("private_internet.content.visual_translator.converse_tool", new=mock):
            scenes = await translate_scenes(
                topic=ABSTRACT_TOPIC,
                narration_script="Some narration about repair and reuse.",
                total_scenes=5,
                target_duration_seconds=100,
            )

        assert len(scenes) == 5
        for scene in scenes:
            final = build_final_prompt(scene)
            assert final.endswith(KLING_STYLE_SUFFIX)
            assert ABSTRACT_TOPIC not in final

    @pytest.mark.anyio
    async def test_forces_tool_and_zero_temperature(self):
        mock = AsyncMock(return_value=(_scene_descriptions(), {}))
        with patch("private_internet.content.visual_translator.converse_tool", new=mock):
            await translate_scenes(
                topic=ABSTRACT_TOPIC, narration_script="x", total_scenes=5,
                target_duration_seconds=100,
            )
        kwargs = mock.call_args.kwargs
        assert kwargs["temperature"] == 0.0
        # tool is the second positional arg to converse_tool(user_prompt, tool, ...)
        assert mock.call_args.args[1]["name"] == VISUAL_TRANSLATOR_TOOL["name"]
        # The user message carries the four required fields.
        user_message = mock.call_args.args[0]
        assert "Topic: " in user_message
        assert "Number of scenes needed: 5" in user_message
        assert "Total video duration target: 100" in user_message

    @pytest.mark.anyio
    async def test_sorts_by_scene_number(self):
        shuffled = {"scene_descriptions": [
            _scene(3, "c"), _scene(1, "a"), _scene(2, "b"),
        ]}
        mock = AsyncMock(return_value=(shuffled, {}))
        with patch("private_internet.content.visual_translator.converse_tool", new=mock):
            scenes = await translate_scenes(
                topic="t", narration_script="x", total_scenes=3, target_duration_seconds=30,
            )
        assert [s["scene_number"] for s in scenes] == [1, 2, 3]

    @pytest.mark.anyio
    async def test_no_tool_output_returns_empty(self):
        mock = AsyncMock(return_value=(None, {}))
        with patch("private_internet.content.visual_translator.converse_tool", new=mock):
            scenes = await translate_scenes(
                topic="t", narration_script="x", total_scenes=5, target_duration_seconds=100,
            )
        assert scenes == []


# ── video_job wiring ───────────────────────────────────────────────

def _topic(name=ABSTRACT_TOPIC) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "slug": "circular-economy"}


class TestTranslateScenesForScript:
    @pytest.mark.anyio
    async def test_slides_backend_skips_translation(self):
        with patch(
            "private_internet.content.jobs.video_job.get_settings",
            return_value=SimpleNamespace(video_backend="slides"),
        ):
            result = await _translate_scenes_for_script(_topic(), _script())
        assert result == [None] * 5

    @pytest.mark.anyio
    async def test_fal_backend_maps_scenes_to_sections(self):
        mock = AsyncMock(return_value=(_scene_descriptions(), {}))
        with patch(
            "private_internet.content.jobs.video_job.get_settings",
            return_value=SimpleNamespace(video_backend="fal"),
        ), patch("private_internet.content.visual_translator.converse_tool", new=mock):
            result = await _translate_scenes_for_script(_topic(), _script())

        assert len(result) == 5
        assert all(s is not None for s in result)
        assert result[0]["scene_number"] == 1

    @pytest.mark.anyio
    async def test_translation_failure_degrades_to_slides(self):
        mock = AsyncMock(side_effect=RuntimeError("bedrock down"))
        with patch(
            "private_internet.content.jobs.video_job.get_settings",
            return_value=SimpleNamespace(video_backend="fal"),
        ), patch("private_internet.content.visual_translator.converse_tool", new=mock):
            result = await _translate_scenes_for_script(_topic(), _script())
        assert result == [None] * 5


class TestSectionVisualSendsTranslatedPrompt:
    @pytest.mark.anyio
    async def test_kling_receives_final_prompt_not_topic(self, tmp_path):
        scene = _scene(1, CONCRETE_PROMPTS[0])
        section = ScriptSection(id="INTRO", text="x", image_prompt=ABSTRACT_TOPIC)
        clip_mock = AsyncMock(return_value=b"mp4-bytes")
        image_gen = MagicMock()

        with patch(
            "private_internet.content.jobs.video_job.get_settings",
            return_value=SimpleNamespace(video_backend="fal"),
        ), patch(
            "private_internet.content.jobs.video_job.generate_video_clip", new=clip_mock
        ):
            # content_type="stories" routes to Kling (get_provider -> "kling"),
            # the only path that still sends prompts to the fal/Kling client.
            path = await _section_visual(
                image_gen, section, {"name": "c"}, 0, "title", str(tmp_path), scene,
                content_type="stories",
            )

        sent_prompt = clip_mock.call_args.args[0]
        assert KLING_STYLE_SUFFIX in sent_prompt
        assert sent_prompt == build_final_prompt(scene)
        # The abstract topic / image_prompt must NEVER reach Kling.
        assert ABSTRACT_TOPIC not in sent_prompt
        assert path.endswith(".mp4")
        image_gen.generate_for_section.assert_not_called()

    @pytest.mark.anyio
    async def test_no_scene_falls_back_to_slide_without_calling_kling(self, tmp_path):
        section = ScriptSection(id="INTRO", text="x", image_prompt=ABSTRACT_TOPIC)
        clip_mock = AsyncMock(return_value=b"mp4-bytes")
        image_gen = MagicMock()
        image_gen.generate_for_section = AsyncMock(return_value=b"png")

        with patch(
            "private_internet.content.jobs.video_job.get_settings",
            return_value=SimpleNamespace(video_backend="fal"),
        ), patch(
            "private_internet.content.jobs.video_job.generate_video_clip", new=clip_mock
        ):
            path = await _section_visual(
                image_gen, section, {"name": "c"}, 0, "title", str(tmp_path), None
            )

        clip_mock.assert_not_called()
        image_gen.generate_for_section.assert_awaited_once()
        assert path.endswith(".png")
