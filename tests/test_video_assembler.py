"""Tests for the shared scene-stitching pipeline (content/video_assembler.py)."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from private_internet.content import video_assembler as va
from private_internet.content.video_assembler import (
    MOOD_FALLBACK_COLORS,
    MAX_CONCURRENT_KLING_CALLS,
    fallback_card_command,
    generate_fallback_card,
    write_concat_manifest,
    translate_visuals_batch,
    chunk_scenes,
    assemble_video,
)


def _scene(n, scene_type="development", duration=8):
    return {
        "scene_number": n,
        "narration_text": f"Narration for scene {n}.",
        "visual_description": f"A quiet beat number {n}",
        "duration_seconds": duration,
        "scene_type": scene_type,
    }


# ── Fallback colour cards ──────────────────────────────────────

class TestFallbackCard:
    def test_semaphore_limit_is_four(self):
        assert MAX_CONCURRENT_KLING_CALLS == 4

    @pytest.mark.parametrize("mood,hex_color", list(MOOD_FALLBACK_COLORS.items()))
    def test_command_embeds_mood_color_and_dimensions(self, mood, hex_color):
        args = fallback_card_command(hex_color, 8, "/tmp/clip.mp4")
        joined = " ".join(args)
        assert f"color=c={hex_color}:size=1920x1080:duration=8" in joined
        assert args[0] == "ffmpeg"
        assert "libx264" in args
        assert args[-1] == "/tmp/clip.mp4"

    def test_command_uses_requested_duration(self):
        args = fallback_card_command("#1A1A28", 10, "/tmp/c.mp4")
        assert "duration=10" in " ".join(args)

    def test_generate_card_maps_mood_to_color(self):
        with patch.object(va, "_run_ffmpeg") as run:
            generate_fallback_card("tense", 8, "/tmp/x.mp4")
        called_args = run.call_args.args[0]
        assert MOOD_FALLBACK_COLORS["tense"] in " ".join(called_args)

    def test_generate_card_unknown_mood_falls_back_to_calm(self):
        with patch.object(va, "_run_ffmpeg") as run:
            generate_fallback_card("nonsense", 8, "/tmp/x.mp4")
        assert MOOD_FALLBACK_COLORS["calm"] in " ".join(run.call_args.args[0])


# ── Concat manifest ────────────────────────────────────────────

class TestConcatManifest:
    def test_manifest_format(self, tmp_path):
        clips = [f"{tmp_path}/clip_0001.mp4", f"{tmp_path}/clip_0002.mp4"]
        manifest = tmp_path / "concat.txt"
        returned = write_concat_manifest(clips, str(manifest))

        assert returned == str(manifest)
        content = manifest.read_text()
        assert content == f"file '{clips[0]}'\nfile '{clips[1]}'\n"

    def test_manifest_one_line_per_clip(self, tmp_path):
        clips = [f"/v/{i}.mp4" for i in range(5)]
        manifest = tmp_path / "c.txt"
        write_concat_manifest(clips, str(manifest))
        lines = manifest.read_text().splitlines()
        assert len(lines) == 5
        assert all(line.startswith("file '") and line.endswith("'") for line in lines)

    def test_empty_manifest(self, tmp_path):
        manifest = tmp_path / "c.txt"
        write_concat_manifest([], str(manifest))
        assert manifest.read_text() == ""


# ── Visual translation helpers ─────────────────────────────────

class TestTranslateAndChunk:
    def test_translate_visuals_batch_one_per_scene(self):
        scenes = [_scene(1), _scene(2, "climax")]
        prompts = translate_visuals_batch(scenes)
        assert len(prompts) == 2
        assert "no text" in prompts[0]
        # climax style language is applied
        assert "dramatic close-up" in prompts[1]

    def test_chunk_scenes_segments_of_fifty(self):
        scenes = [_scene(i) for i in range(1, 121)]
        chunks = chunk_scenes(scenes, size=50)
        assert [len(c) for c in chunks] == [50, 50, 20]

    def test_chunk_scenes_empty(self):
        assert chunk_scenes([]) == [[]]


# ── assemble_video resilience ──────────────────────────────────

def _patch_pipeline(clip_side_effect):
    """Patch every external dependency of assemble_video. `clip_side_effect`
    drives the per-clip provider call — both the Kling (fal) and Wan2.1 clients
    are wired to it, so a test works whatever the content_type routes to.
    Returns a dict of the mocks for assertions."""
    recorded = {"fallback_cards": 0, "concat_written": False, "uploaded_key": None}

    async def wan_side_effect(prompt, duration_seconds=5, width=1280, height=720):
        # Adapt the Wan2.1 client signature to the shared clip side effect.
        return await clip_side_effect(
            prompt, duration=duration_seconds, aspect_ratio="16:9"
        )

    def fake_run_ffmpeg(args):
        # Track fallback-card invocations by their lavfi color source.
        if any("lavfi" in a for a in args):
            recorded["fallback_cards"] += 1
        # Create the output file (last arg) so downstream open()/probe succeeds.
        Path(args[-1]).write_bytes(b"")

    def fake_write_manifest(clip_paths, manifest_path):
        recorded["concat_written"] = True
        recorded["clip_count"] = len(clip_paths)
        return manifest_path

    class FakeStore:
        cdn_base = "https://cdn.example.com"
        def _upload(self, key, body, ctype):
            recorded["uploaded_key"] = key
            return f"https://cdn.example.com/{key}"

    patches = [
        patch.object(va, "_check_ffmpeg", lambda: None),
        patch.object(va, "_run_ffmpeg", side_effect=fake_run_ffmpeg),
        patch.object(va, "write_concat_manifest", side_effect=fake_write_manifest),
        patch.object(va, "translate_scenes", new=AsyncMock(return_value=[])),
        patch.object(va, "generate_video_clip", new=AsyncMock(side_effect=clip_side_effect)),
        patch.object(va._wan_client, "generate_clip", new=AsyncMock(side_effect=wan_side_effect)),
        patch.object(va, "_synthesize_narration", lambda *a, **k: None),
        patch.object(va, "AssetStore", FakeStore),
    ]
    return patches, recorded


class TestAssembleVideoResilience:
    @pytest.mark.anyio
    async def test_continues_when_one_clip_fails(self):
        scenes = [_scene(1, "establishing"), _scene(2, "climax"), _scene(3, "resolution")]

        # Scene 2's clip raises; scenes 1 and 3 succeed.
        async def clip(prompt, *, duration, aspect_ratio):
            if "number 2" in prompt or "beat number 2" in prompt:
                raise RuntimeError("kling rate limited")
            return b"fake-mp4-bytes"

        # The translator returns [], so prompts come from translate_visuals_batch,
        # which embeds the visual_description ("beat number N").
        patches, recorded = _patch_pipeline(clip)
        for p in patches:
            p.start()
        try:
            key = await assemble_video(
                scenes=scenes,
                narration_text="full narration",
                language_code="en",
                output_s3_key="content/videos/v1/video.mp4",
                content_type="signal",
            )
        finally:
            for p in patches:
                p.stop()

        # Assembly completed and uploaded despite the failed clip.
        assert key == "content/videos/v1/video.mp4"
        assert recorded["uploaded_key"] == "content/videos/v1/video.mp4"
        # Exactly one fallback card was generated (for scene 2).
        assert recorded["fallback_cards"] == 1
        # All three clips made it into the concat manifest.
        assert recorded["concat_written"] is True
        assert recorded["clip_count"] == 3

    @pytest.mark.anyio
    async def test_progress_callback_fires_after_every_clip(self):
        scenes = [_scene(i) for i in range(1, 5)]
        seen = []

        async def clip(prompt, *, duration, aspect_ratio):
            return b"ok"

        patches, _ = _patch_pipeline(clip)
        for p in patches:
            p.start()
        try:
            await assemble_video(
                scenes=scenes,
                narration_text="n",
                language_code="en",
                output_s3_key="k.mp4",
                content_type="stories",
                on_progress=lambda patch: seen.append(patch),
            )
        finally:
            for p in patches:
                p.stop()

        # One {"clips_generated": k} update per clip (4 clips).
        clip_updates = [p for p in seen if "clips_generated" in p and p["clips_generated"] > 0]
        assert len(clip_updates) == 4
        assert {p["clips_generated"] for p in clip_updates} == {1, 2, 3, 4}
        # total_scenes was announced before clip generation began.
        assert any(p.get("total_scenes") == 4 for p in seen)

    @pytest.mark.anyio
    async def test_temp_dir_kept_on_upload_failure(self, tmp_path):
        scenes = [_scene(1)]

        async def clip(prompt, *, duration, aspect_ratio):
            return b"ok"

        class FailingStore:
            cdn_base = "https://cdn"
            def _upload(self, *a, **k):
                raise RuntimeError("s3 down")

        created_dirs = []
        real_mkdtemp = va.tempfile.mkdtemp

        def tracking_mkdtemp(*a, **k):
            d = real_mkdtemp(*a, **k)
            created_dirs.append(d)
            return d

        patches, _ = _patch_pipeline(clip)
        patches.append(patch.object(va, "AssetStore", FailingStore))
        patches.append(patch.object(va.tempfile, "mkdtemp", side_effect=tracking_mkdtemp))
        for p in patches:
            p.start()
        try:
            with pytest.raises(RuntimeError, match="s3 down"):
                await assemble_video(
                    scenes=scenes,
                    narration_text="n",
                    language_code="en",
                    output_s3_key="k.mp4",
                    content_type="signal",
                )
        finally:
            for p in patches:
                p.stop()

        # On failure the temp dir is kept for debugging (not cleaned up).
        assert created_dirs and Path(created_dirs[0]).exists()
        # cleanup so we don't leak in the test environment
        import shutil
        shutil.rmtree(created_dirs[0], ignore_errors=True)
