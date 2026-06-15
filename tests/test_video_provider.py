"""Tests for hybrid video provider routing (Wan2.1 + Kling).

Covers content/video_provider.py (the single source of truth for routing + cost)
and the per-provider fallback hierarchy in content/video_assembler.py:

    SIGNAL / PULSE → Wan2.1 → colour card   (NEVER Kling — cost protection)
    STORIES        → Kling  → Wan2.1 → colour card
"""

import pytest
from unittest.mock import patch, AsyncMock

from private_internet.content import video_provider as vp
from private_internet.content import video_assembler as va
from private_internet.content.video_provider import (
    VIDEO_PROVIDER_MAP,
    ESTIMATED_COST_EUR,
    get_provider,
    log_generation_cost,
)
from private_internet.content.video_assembler import (
    _generate_clip_with_fallback,
    assemble_video,
)
from private_internet.content.replicate_wan_client import Wan2GenerationError


# ── get_provider routing (single source of truth) ──────────────

class TestGetProvider:
    @pytest.mark.parametrize("content_type,expected", [
        ("stories", "kling"),
        ("signal",  "wan2"),
        ("pulse",   "wan2"),
    ])
    def test_returns_correct_provider(self, content_type, expected):
        assert get_provider(content_type) == expected

    def test_map_is_exactly_three_content_types(self):
        assert set(VIDEO_PROVIDER_MAP) == {"stories", "signal", "pulse"}

    def test_unknown_content_type_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown content_type"):
            get_provider("podcast")

    def test_valueerror_lists_valid_types(self):
        with pytest.raises(ValueError) as exc:
            get_provider("")
        for ct in ("stories", "signal", "pulse"):
            assert ct in str(exc.value)


# ── Cost logging ───────────────────────────────────────────────

class TestCostLogging:
    def test_cost_constants_present(self):
        assert ESTIMATED_COST_EUR["wan2"] < ESTIMATED_COST_EUR["kling"]

    def test_log_generation_cost_emits_provider_and_cost(self):
        with patch.object(vp.logger, "info") as info:
            log_generation_cost("wan2", "signal", 3, is_fallback=False)
        info.assert_called_once()
        extra = info.call_args.kwargs["extra"]
        assert extra["provider"] == "wan2"
        assert extra["content_type"] == "signal"
        assert extra["scene_number"] == 3
        assert extra["is_fallback"] is False
        assert extra["estimated_cost_eur"] == ESTIMATED_COST_EUR["wan2"]

    def test_unknown_provider_costs_zero(self):
        with patch.object(vp.logger, "info") as info:
            log_generation_cost("midjourney", "signal", 1, is_fallback=True)
        assert info.call_args.kwargs["extra"]["estimated_cost_eur"] == 0.0


# ── Per-provider fallback hierarchy ────────────────────────────

class TestFallbackHierarchy:
    @pytest.mark.anyio
    async def test_wan2_success(self):
        with patch.object(va._wan_client, "generate_clip",
                          new=AsyncMock(return_value=b"wan-bytes")) as wan, \
             patch.object(va, "generate_video_clip", new=AsyncMock()) as kling:
            data, used, is_fallback = await _generate_clip_with_fallback(
                "wan2", "a prompt", 8
            )
        assert (data, used, is_fallback) == (b"wan-bytes", "wan2", False)
        wan.assert_awaited_once()
        # SIGNAL/PULSE must NEVER touch Kling.
        kling.assert_not_called()

    @pytest.mark.anyio
    async def test_wan2_failure_uses_card_and_never_calls_kling(self):
        """A failed SIGNAL/PULSE clip returns no bytes (caller renders a colour
        card) and must NOT trigger a Kling API call — the cost model depends on
        this."""
        with patch.object(va._wan_client, "generate_clip",
                          new=AsyncMock(side_effect=Wan2GenerationError("boom"))), \
             patch.object(va, "generate_video_clip", new=AsyncMock()) as kling:
            data, used, is_fallback = await _generate_clip_with_fallback(
                "wan2", "a prompt", 8
            )
        assert data is None          # → caller renders a colour card
        assert used is None
        assert is_fallback is True
        kling.assert_not_called()    # absolute constraint

    @pytest.mark.anyio
    async def test_kling_success(self):
        with patch.object(va, "generate_video_clip",
                          new=AsyncMock(return_value=b"kling-bytes")) as kling, \
             patch.object(va._wan_client, "generate_clip", new=AsyncMock()) as wan:
            data, used, is_fallback = await _generate_clip_with_fallback(
                "kling", "a prompt", 10
            )
        assert (data, used, is_fallback) == (b"kling-bytes", "kling", False)
        kling.assert_awaited_once()
        wan.assert_not_called()

    @pytest.mark.anyio
    async def test_kling_failure_falls_back_to_wan2(self):
        with patch.object(va, "generate_video_clip",
                          new=AsyncMock(side_effect=RuntimeError("kling down"))), \
             patch.object(va._wan_client, "generate_clip",
                          new=AsyncMock(return_value=b"wan-bytes")) as wan:
            data, used, is_fallback = await _generate_clip_with_fallback(
                "kling", "a prompt", 10
            )
        # STORIES degrades to Wan2.1 before the colour card; cost reflects wan2.
        assert (data, used, is_fallback) == (b"wan-bytes", "wan2", True)
        wan.assert_awaited_once()

    @pytest.mark.anyio
    async def test_kling_then_wan2_both_fail_uses_card(self):
        with patch.object(va, "generate_video_clip",
                          new=AsyncMock(side_effect=RuntimeError("kling down"))), \
             patch.object(va._wan_client, "generate_clip",
                          new=AsyncMock(side_effect=Wan2GenerationError("wan down"))):
            data, used, is_fallback = await _generate_clip_with_fallback(
                "kling", "a prompt", 10
            )
        assert data is None          # → caller renders a colour card
        assert used is None
        assert is_fallback is True


# ── Cost logging fires during assembly ─────────────────────────

def _scene(n):
    return {
        "scene_number": n,
        "narration_text": f"Narration {n}.",
        "visual_description": f"A beat number {n}",
        "duration_seconds": 8,
        "scene_type": "development",
    }


class TestAssemblyLogsCost:
    @pytest.mark.anyio
    async def test_cost_logged_once_per_successful_clip(self):
        """log_generation_cost fires for each clip a provider actually produces
        (SIGNAL → wan2). A clip that degrades to a colour card logs no cost."""
        from tests.test_video_assembler import _patch_pipeline

        scenes = [_scene(1), _scene(2), _scene(3)]

        async def clip(prompt, *, duration, aspect_ratio):
            return b"ok"

        cost_calls = []
        patches, _ = _patch_pipeline(clip)
        patches.append(patch.object(
            va, "log_generation_cost",
            side_effect=lambda *a, **k: cost_calls.append((a, k)),
        ))
        for p in patches:
            p.start()
        try:
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

        # One cost log per successful clip, all attributed to wan2 for SIGNAL.
        assert len(cost_calls) == 3
        assert all(args[0] == "wan2" for args, _ in cost_calls)
        assert all(args[1] == "signal" for args, _ in cost_calls)
