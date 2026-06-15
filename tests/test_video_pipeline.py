import json
import uuid
import subprocess
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock, call

# Image gen dispatches by IMAGE_BACKEND (default fal.ai); these tests exercise the
# Bedrock/Nova-Canvas path, so force that backend.
_BEDROCK = SimpleNamespace(image_backend="bedrock", aws_region="eu-central-1")

from private_internet.content.video_generator import (
    VideoScriptGenerator,
    VideoImageGenerator,
    VideoScript,
    ScriptSection,
    SECTION_IDS,
)
from private_internet.content.polly_engine import PollyEngine, NON_NEURAL_VOICES
from private_internet.content.ffmpeg_assembler import VideoAssembler, VideoAssemblyError
from private_internet.content.jobs.video_job import generate_video, generate_videos_batch


# ── Fixtures ───────────────────────────────────────────────────

def _creator(slug="maksim-volkov", voice="Maxim", lang="ru-RU"):
    return {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "style_prompt": "Write like a dry Soviet-era intellectual.",
        "polly_voice_id": voice,
        "polly_language_code": lang,
        "score": 0.7,
        "is_active": True,
    }


def _topic(name="The collapse of EU industrial policy"):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "slug": "eu-industrial-policy",
        "weight": 0.9,
    }


def _script_json():
    return json.dumps({
        "title": "The Quiet Collapse",
        "description": "A look at EU industrial policy. It is not going well.",
        "sections": [
            {"id": sid, "text": f"Narration for {sid}.", "image_prompt": f"Image for {sid}"}
            for sid in SECTION_IDS
        ],
    })


def _script() -> VideoScript:
    data = json.loads(_script_json())
    return VideoScript(
        title=data["title"],
        description=data["description"],
        sections=[ScriptSection(**s) for s in data["sections"]],
    )


# ── VideoScriptGenerator ───────────────────────────────────────

class TestVideoScriptGenerator:
    @pytest.mark.anyio
    async def test_generates_five_section_script(self):
        generator = VideoScriptGenerator()
        with patch(
            "private_internet.content.video_generator.converse_text",
            new=AsyncMock(return_value=(_script_json(), {})),
        ):
            script = await generator.generate(
                _topic(), _creator(), [{"url": "https://x.com", "title": "T", "summary": "S"}]
            )

        assert script.title == "The Quiet Collapse"
        assert [s.id for s in script.sections] == SECTION_IDS
        assert all(s.text and s.image_prompt for s in script.sections)

    @pytest.mark.anyio
    async def test_strips_markdown_fences(self):
        generator = VideoScriptGenerator()
        fenced = f"```json\n{_script_json()}\n```"
        with patch(
            "private_internet.content.video_generator.converse_text",
            new=AsyncMock(return_value=(fenced, {})),
        ):
            script = await generator.generate(_topic(), _creator(), [])
        assert len(script.sections) == 5

    @pytest.mark.anyio
    async def test_rejects_out_of_spec_sections(self):
        generator = VideoScriptGenerator()
        bad = json.dumps({
            "title": "t",
            "description": "d",
            "sections": [{"id": "INTRO", "text": "x", "image_prompt": "y"}],
        })
        with patch(
            "private_internet.content.video_generator.converse_text",
            new=AsyncMock(return_value=(bad, {})),
        ):
            with pytest.raises(ValueError, match="out of spec"):
                await generator.generate(_topic(), _creator(), [])

    @pytest.mark.anyio
    async def test_creator_style_in_system_prompt(self):
        generator = VideoScriptGenerator()
        mock_converse = AsyncMock(return_value=(_script_json(), {}))
        with patch(
            "private_internet.content.video_generator.converse_text", new=mock_converse
        ):
            await generator.generate(_topic(), _creator(), [])
        system_prompt = mock_converse.call_args.kwargs["system_prompt"]
        assert "dry Soviet-era intellectual" in system_prompt
        assert mock_converse.call_args.kwargs["temperature"] == 0.0


# ── VideoImageGenerator ────────────────────────────────────────

class TestVideoImageGenerator:
    @pytest.mark.anyio
    async def test_section_image_uses_video_sizing(self):
        generator = VideoImageGenerator()
        section = ScriptSection(id="SECTION_1", text="x", image_prompt="A rusting factory")
        with patch(
            "private_internet.content.image_generator.get_settings", return_value=_BEDROCK
        ), patch.object(
            generator, "_invoke_nova_canvas", new=AsyncMock(return_value=b"png")
        ) as mock_canvas:
            result = await generator.generate_for_section(section, _creator())

        assert result == b"png"
        kwargs = mock_canvas.call_args.kwargs
        assert kwargs["width"] == 1280
        assert kwargs["height"] == 720
        prompt = mock_canvas.call_args.args[0]
        assert prompt.startswith("A rusting factory")
        assert "cinematic, 16:9, dark editorial style, no text" in prompt

    @pytest.mark.anyio
    async def test_thumbnail_uses_intro_prompt(self):
        generator = VideoImageGenerator()
        with patch(
            "private_internet.content.image_generator.get_settings", return_value=_BEDROCK
        ), patch.object(
            generator, "_invoke_nova_canvas", new=AsyncMock(return_value=b"thumb")
        ) as mock_canvas:
            result = await generator.generate_thumbnail(_script(), _creator())

        assert result == b"thumb"
        prompt = mock_canvas.call_args.args[0]
        assert prompt.startswith("Image for INTRO")
        assert "bold title overlay style, high contrast" in prompt


# ── PollyEngine ────────────────────────────────────────────────

class TestPollyEngine:
    def _engine_with_mock_polly(self):
        with patch("private_internet.content.polly_engine.boto3") as mock_boto3:
            mock_polly = MagicMock()
            stream = MagicMock()
            stream.read.return_value = b"mp3-bytes"
            mock_polly.synthesize_speech.return_value = {"AudioStream": stream}
            mock_boto3.client.return_value = mock_polly
            engine = PollyEngine()
        return engine, mock_polly

    def test_neural_engine_for_neural_voice(self, tmp_path):
        engine, mock_polly = self._engine_with_mock_polly()
        out = str(tmp_path / "audio.mp3")
        with patch.object(PollyEngine, "_probe_duration_ms", return_value=12500):
            duration = engine.synthesize_section("Hello", "Joanna", "en-US", out)

        assert duration == 12500
        assert mock_polly.synthesize_speech.call_args.kwargs["Engine"] == "neural"
        with open(out, "rb") as f:
            assert f.read() == b"mp3-bytes"

    def test_standard_engine_for_non_neural_voice(self, tmp_path):
        assert "Maxim" in NON_NEURAL_VOICES
        engine, mock_polly = self._engine_with_mock_polly()
        out = str(tmp_path / "audio.mp3")
        with patch.object(PollyEngine, "_probe_duration_ms", return_value=1000):
            engine.synthesize_section("Привет", "Maxim", "ru-RU", out)
        assert mock_polly.synthesize_speech.call_args.kwargs["Engine"] == "standard"

    def test_probe_duration_parses_ffprobe_json(self):
        ffprobe_out = json.dumps({"format": {"duration": "12.480000"}}).encode()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=ffprobe_out)
        with patch(
            "private_internet.content.polly_engine.subprocess.run",
            return_value=completed,
        ):
            assert PollyEngine._probe_duration_ms("/tmp/x.mp3") == 12480

    def test_get_total_duration(self):
        engine, _ = self._engine_with_mock_polly()
        assert engine.get_total_duration([1000, 2500, 500]) == 4000


# ── VideoAssembler ─────────────────────────────────────────────

class TestVideoAssembler:
    def _fake_subprocess(self, durations):
        """ffprobe returns queued durations; ffmpeg succeeds silently."""
        duration_iter = iter(durations)

        def fake_run(args, check, capture_output):
            if args[0] == "ffprobe":
                out = json.dumps({"format": {"duration": str(next(duration_iter))}}).encode()
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=out)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"")

        return fake_run

    def test_assemble_builds_clips_and_concatenates(self):
        sections = _script().sections
        images = [f"/tmp/img_{i}.png" for i in range(5)]
        audios = [f"/tmp/audio_{i}.mp3" for i in range(5)]
        recorded = []

        fake = self._fake_subprocess([10.0] * 5 + [120.0])

        def recording_run(args, check, capture_output):
            recorded.append(args)
            return fake(args, check, capture_output)

        with patch(
            "private_internet.content.ffmpeg_assembler.subprocess.run",
            side_effect=recording_run,
        ):
            duration = VideoAssembler().assemble(sections, images, audios, "/tmp/out.mp4")

        assert duration == 120
        ffmpeg_calls = [a for a in recorded if a[0] == "ffmpeg"]
        # 5 section clips + 1 concat
        assert len(ffmpeg_calls) == 6
        section_cmd = ffmpeg_calls[0]
        vf = section_cmd[section_cmd.index("-vf") + 1]
        assert "zoompan" in vf
        assert "s=1280x720" in vf
        assert "-shortest" in section_cmd
        concat_cmd = ffmpeg_calls[-1]
        assert "concat" in concat_cmd
        assert "/tmp/out.mp4" in concat_cmd

    def test_mismatched_inputs_raise(self):
        with pytest.raises(VideoAssemblyError, match="equal length"):
            VideoAssembler().assemble(_script().sections, ["one.png"], [], "/tmp/out.mp4")

    def test_ffmpeg_failure_raises_assembly_error(self):
        def failing_run(args, check, capture_output):
            if args[0] == "ffprobe":
                out = json.dumps({"format": {"duration": "10.0"}}).encode()
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=out)
            raise subprocess.CalledProcessError(1, args, stderr=b"boom")

        with patch(
            "private_internet.content.ffmpeg_assembler.subprocess.run",
            side_effect=failing_run,
        ):
            with pytest.raises(VideoAssemblyError, match="boom"):
                VideoAssembler().assemble(
                    _script().sections,
                    [f"/tmp/img_{i}.png" for i in range(5)],
                    [f"/tmp/audio_{i}.mp3" for i in range(5)],
                    "/tmp/out.mp4",
                )


# ── generate_video orchestrator ────────────────────────────────

def _recording_conn():
    """Connection mock that records all cursor.execute() SQL."""
    conn = MagicMock()
    executed = []
    cursor = MagicMock()

    def record_execute(sql, params=None):
        executed.append((" ".join(sql.split()), params))

    cursor.execute.side_effect = record_execute
    conn.cursor.return_value = cursor
    return conn, executed


def _patched_pipeline(conn, script=None, fail_script=False):
    """Patch every external dependency of video_job. Returns the patch list."""
    script = script or _script()

    script_gen = MagicMock()
    if fail_script:
        script_gen.generate = AsyncMock(side_effect=RuntimeError("LLM exploded"))
    else:
        script_gen.generate = AsyncMock(return_value=script)

    image_gen = MagicMock()
    image_gen.generate_for_section = AsyncMock(return_value=b"png-bytes")
    image_gen.generate_thumbnail = AsyncMock(return_value=b"thumb-bytes")

    polly = MagicMock()
    polly.synthesize_section.return_value = 10000

    assembler = MagicMock()
    assembler.assemble.return_value = 118

    asset_store = MagicMock()
    asset_store.upload_video.return_value = "https://cdn.example/video.mp4"
    asset_store.upload_thumbnail.return_value = "https://cdn.example/thumb.png"

    selector = MagicMock()
    selector.select_for_topic.return_value = _creator()

    base = "private_internet.content.jobs.video_job"
    return [
        patch(f"{base}._connect", return_value=conn),
        patch(f"{base}._select_topic", return_value=_topic()),
        patch(f"{base}._fetch_research", return_value=[]),
        patch(f"{base}.CreatorSelector", return_value=selector),
        patch(f"{base}.VideoScriptGenerator", return_value=script_gen),
        patch(f"{base}.VideoImageGenerator", return_value=image_gen),
        # TTS via the engine factory; force the slide path so no fal video is called.
        patch(f"{base}.get_tts_engine", return_value=polly),
        patch(f"{base}.get_settings", return_value=SimpleNamespace(video_backend="slides")),
        patch(f"{base}.VideoAssembler", return_value=assembler),
        patch(f"{base}.AssetStore", return_value=asset_store),
    ], polly, assembler, asset_store


class TestGenerateVideo:
    @pytest.mark.anyio
    async def test_happy_path_status_transitions_and_cleanup(self):
        conn, executed = _recording_conn()
        patches, polly, assembler, asset_store = _patched_pipeline(conn)

        with patch(
            "private_internet.content.jobs.video_job.shutil.rmtree"
        ) as mock_rmtree:
            for p in patches:
                p.start()
            try:
                video_id = await generate_video(user_id="u1")
            finally:
                for p in patches:
                    p.stop()

        # processing → ready
        inserts = [sql for sql, _ in executed if "INSERT INTO content_videos" in sql]
        assert len(inserts) == 1 and "'processing'" in inserts[0]
        updates = [(sql, params) for sql, params in executed if "UPDATE content_videos" in sql]
        assert len(updates) == 1 and "status = 'ready'" in updates[0][0]
        # final update carries urls + duration
        params = updates[0][1]
        assert "https://cdn.example/video.mp4" in params
        assert "https://cdn.example/thumb.png" in params
        assert 118 in params

        # topic usage bumped
        assert any("UPDATE content_topics" in sql for sql, _ in executed)

        # 5 narration sections, sequential polly calls
        assert polly.synthesize_section.call_count == 5
        # assembled then uploaded
        assembler.assemble.assert_called_once()
        asset_store.upload_video.assert_called_once()
        asset_store.upload_thumbnail.assert_called_once_with(b"thumb-bytes", video_id)
        # /tmp/{video_id} cleaned up
        mock_rmtree.assert_called_once_with(f"/tmp/{video_id}", ignore_errors=True)

    @pytest.mark.anyio
    async def test_failure_marks_video_failed_and_reraises(self):
        conn, executed = _recording_conn()
        patches, *_ = _patched_pipeline(conn, fail_script=True)

        with patch("private_internet.content.jobs.video_job.shutil.rmtree") as mock_rmtree:
            for p in patches:
                p.start()
            try:
                with pytest.raises(RuntimeError, match="LLM exploded"):
                    await generate_video(user_id="u1")
            finally:
                for p in patches:
                    p.stop()

        failed_updates = [sql for sql, _ in executed if "status = 'failed'" in sql]
        assert len(failed_updates) == 1
        mock_rmtree.assert_called_once()
        conn.close.assert_called_once()

    @pytest.mark.anyio
    async def test_batch_runs_sequentially_and_counts_failures(self):
        calls = []

        async def fake_generate(topic_id=None, *, user_id, duration_band="standard"):
            calls.append(topic_id)
            if len(calls) == 2:
                raise RuntimeError("second one fails")
            return f"video-{len(calls)}"

        with patch(
            "private_internet.content.jobs.video_job.generate_long_video",
            side_effect=fake_generate,
        ):
            result = await generate_videos_batch(count=3, user_id="u1")

        assert result == {"created": ["video-1", "video-3"], "failed": 1}

    @pytest.mark.anyio
    async def test_batch_with_pinned_topic_runs_once(self):
        mock_gen = AsyncMock(return_value="video-1")
        with patch(
            "private_internet.content.jobs.video_job.generate_long_video", new=mock_gen
        ):
            result = await generate_videos_batch(count=3, topic_id="t-1", user_id="u1")

        assert mock_gen.call_count == 1
        # Scheduled feed uses the cheap short-form WAN band.
        assert mock_gen.call_args == call("t-1", user_id="u1", duration_band="short")
        assert result["created"] == ["video-1"]
