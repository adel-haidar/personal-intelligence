"""Tests for the fal.ai video clip call — duration snapping in particular.

The fal call owns duration policy: it snaps each requested per-scene duration to
a value the configured model actually supports (`fal_video_durations`). Callers
pass the real requested seconds and never need to know the model's clip menu.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from private_internet.content import fal_video
from private_internet.content.fal_video import _snap_duration, _supported_durations


class TestSnapDuration:
    @pytest.mark.parametrize("requested,expected", [
        (5, 5), (10, 10),
        (8, 10),    # tie-ish between 5 and 10 → longer, never under-run narration
        (7, 5),     # |7-5|=2 < |7-10|=3
        (3, 5),     # below the menu → nearest (5)
        (99, 10),   # above the menu → nearest (10)
    ])
    def test_kling_menu_5_10(self, requested, expected):
        assert _snap_duration(requested, [5, 10]) == expected

    @pytest.mark.parametrize("requested,expected", [(5, 5), (8, 8), (10, 10), (7, 8)])
    def test_veo3_menu_5_8_10(self, requested, expected):
        assert _snap_duration(requested, [5, 8, 10]) == expected


class TestSupportedDurations:
    @pytest.mark.parametrize("raw,expected", [
        ("5,10", [5, 10]),
        ("5,8,10", [5, 8, 10]),
        ("10,5,5", [5, 10]),      # deduped + sorted
        (" 5 , 8 ", [5, 8]),      # whitespace tolerated
        ("", [5]),                # empty → safe default
        ("garbage", [5]),         # non-numeric → safe default
    ])
    def test_parses_setting(self, raw, expected):
        with patch.object(
            fal_video, "get_settings",
            return_value=SimpleNamespace(fal_video_durations=raw),
        ):
            assert _supported_durations() == expected


class TestGenerateVideoClipSendsSnappedDuration:
    @pytest.mark.anyio
    async def test_eight_seconds_snaps_to_ten_for_kling(self):
        """An 8s request against the default Kling menu must be sent as '10'."""
        captured = {}

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload
            def raise_for_status(self):
                pass
            def json(self):
                return self._payload
            @property
            def content(self):
                return b"mp4-bytes"

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def post(self, url, json, headers):
                captured["duration"] = json["duration"]
                return FakeResp({"request_id": "r1", "status_url": "s", "response_url": "x"})
            async def get(self, url, headers=None):
                if url == "s":
                    return FakeResp({"status": "COMPLETED"})
                if url == "x":
                    return FakeResp({"video": {"url": "http://clip"}})
                return FakeResp({})

        settings = SimpleNamespace(
            fal_api_key="k",
            fal_video_model="fal-ai/kling-video/v1/standard/text-to-video",
            fal_video_durations="5,10",
        )
        with patch.object(fal_video, "get_settings", return_value=settings), \
             patch.object(fal_video.httpx, "AsyncClient", return_value=FakeClient()), \
             patch.object(fal_video.asyncio, "sleep", new=_anoop):
            data = await fal_video.generate_video_clip("a man repairs a lamp", duration=8)

        assert data == b"mp4-bytes"
        assert captured["duration"] == "10"


async def _anoop(*_a, **_k):
    return None
