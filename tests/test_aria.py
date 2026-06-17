"""ARIA module unit tests — no network, no DB.

Tests cover:
- compute_waveform: returns exactly num_bars floats in [0.0, 1.0].
- queue_next logic: all four tiers verified with pure-Python stubs.
- Playlist auto-grouping by mood: pure-Python grouping function.
"""

import math
import uuid
from unittest.mock import MagicMock, patch

import pytest

# ── compute_waveform ───────────────────────────────────────────────────────────

from private_internet.content.aria.waveform import compute_waveform, _samples_to_bars


class TestComputeWaveform:
    def _sine_audio(self, n_samples: int = 44100) -> list[float]:
        """Generate a simple sine-wave sample list (not real mp3 — used to test
        _samples_to_bars directly so we avoid pydub/ffmpeg in CI)."""
        import math
        return [math.sin(2 * math.pi * 440 * i / 44100) for i in range(n_samples)]

    def test_returns_200_bars_by_default(self):
        samples = self._sine_audio(44100)
        bars = _samples_to_bars(samples, 200)
        assert len(bars) == 200

    def test_custom_bar_count(self):
        samples = self._sine_audio(1000)
        bars = _samples_to_bars(samples, 50)
        assert len(bars) == 50

    def test_all_bars_in_0_1(self):
        samples = self._sine_audio(44100)
        bars = _samples_to_bars(samples, 200)
        for b in bars:
            assert 0.0 <= b <= 1.0, f"Bar {b} out of range"

    def test_peak_bar_is_1(self):
        samples = self._sine_audio(44100)
        bars = _samples_to_bars(samples, 200)
        assert max(bars) == pytest.approx(1.0, abs=1e-6)

    def test_empty_audio_returns_zeros(self):
        bars = compute_waveform(b"", num_bars=200)
        assert bars == [0.0] * 200
        assert len(bars) == 200

    def test_zero_bars_returns_empty_list(self):
        bars = compute_waveform(b"\x00" * 100, num_bars=0)
        assert bars == []

    def test_short_audio_returns_correct_length(self):
        # Very short audio (fewer samples than bars) — must still return num_bars items.
        samples = [0.5, -0.5, 0.3]
        bars = _samples_to_bars(samples, 200)
        assert len(bars) == 200

    def test_silent_audio_all_zeros(self):
        samples = [0.0] * 1000
        bars = _samples_to_bars(samples, 10)
        assert all(b == 0.0 for b in bars)

    def test_compute_waveform_with_pydub_failure_uses_fallback(self):
        """When pydub raises, the audioop fallback must still return num_bars floats."""
        from private_internet.content.aria.waveform import _audioop_decode, _samples_to_bars

        # Simulate pydub unavailable by patching the import inside the module.
        with patch(
            "private_internet.content.aria.waveform._pydub_decode",
            side_effect=ImportError("no pydub"),
        ):
            # Provide enough bytes for the audioop path.
            audio = b"\x80" * 500 + b"\xff" * 500
            bars = compute_waveform(audio, num_bars=100)
        assert len(bars) == 100
        assert all(0.0 <= b <= 1.0 for b in bars)


# ── queue_next (pure-Python tier logic) ───────────────────────────────────────

# We test the logic in isolation by monkey-patching the DB helper functions.
# The queue_next function in db.py calls: get_track, list_tracks,
# recently_played_track_ids, _all_played_track_ids, _least_recently_played.


def _make_track(track_id: str, mood: str = "calm", status: str = "ready") -> dict:
    return {
        "id": track_id,
        "user_id": "user-1",
        "title": f"Track {track_id[:4]}",
        "mood": mood,
        "status": status,
        "genre": "ambient",
        "topic_category": "focus",
        "duration_seconds": 120,
        "audio_s3_key": f"aria/tracks/{track_id}/audio.mp3",
        "waveform_s3_key": f"aria/tracks/{track_id}/waveform.json",
        "art_s3_key": None,
        "lyrics": "",
        "bpm": 90,
        "musical_key": "C major",
        "instruments": [],
        "brain_topic_ids": [],
        "is_liked": False,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


_DB_MODULE = "private_internet.content.aria.db"


class TestQueueNextLogic:
    """Tests the four-tier queue_next selection logic without touching the DB."""

    def _patch_db(
        self,
        all_tracks: list[dict],
        recently_played_ids: set[str] | None = None,
        all_played_ids: set[str] | None = None,
        least_recent: dict | None = None,
    ):
        """Return a list of context-manager patches for the DB helpers."""
        recently_played_ids = recently_played_ids or set()
        all_played_ids = all_played_ids or set()

        def fake_get_track(tid, *, user_id):
            return next((t for t in all_tracks if str(t["id"]) == tid), None)

        def fake_list_tracks(*, user_id, mood=None, topic_category=None, status="ready", limit=50, offset=0):
            rows = [t for t in all_tracks if t["status"] == status]
            if mood:
                rows = [t for t in rows if t["mood"] == mood]
            return rows[:limit]

        return [
            patch(f"{_DB_MODULE}.get_track", side_effect=fake_get_track),
            patch(f"{_DB_MODULE}.list_tracks", side_effect=fake_list_tracks),
            patch(f"{_DB_MODULE}.recently_played_track_ids", return_value=recently_played_ids),
            patch(f"{_DB_MODULE}._all_played_track_ids", return_value=all_played_ids),
            patch(f"{_DB_MODULE}._least_recently_played", return_value=least_recent),
        ]

    def _run_with_patches(self, patches, **queue_kwargs):
        from private_internet.content.aria.db import queue_next
        for p in patches:
            p.start()
        try:
            return queue_next(user_id="user-1", **queue_kwargs)
        finally:
            for p in patches:
                p.stop()

    def test_tier1_explicit_queue_returns_first_unplayed(self):
        t1 = _make_track("aaaa-0001")
        t2 = _make_track("aaaa-0002")
        patches = self._patch_db(
            all_tracks=[t1, t2],
            recently_played_ids={"aaaa-0001"},  # t1 played recently
        )
        result = self._run_with_patches(
            patches,
            explicit_queue=["aaaa-0001", "aaaa-0002"],
        )
        assert result is not None
        assert str(result["id"]) == "aaaa-0002"

    def test_tier2_same_mood_not_recently_played(self):
        current = _make_track("aaaa-cur0", mood="focus")
        same_mood = _make_track("aaaa-0003", mood="focus")
        diff_mood = _make_track("aaaa-0004", mood="calm")
        patches = self._patch_db(
            all_tracks=[current, same_mood, diff_mood],
            recently_played_ids={"aaaa-cur0"},  # current was played, same_mood was not
        )
        result = self._run_with_patches(
            patches,
            current_track_id="aaaa-cur0",
        )
        assert result is not None
        assert str(result["id"]) == "aaaa-0003"
        assert result["mood"] == "focus"

    def test_tier3_unplayed_track_when_all_same_mood_played(self):
        current = _make_track("aaaa-cur1", mood="calm")
        same_mood_also_recent = _make_track("aaaa-sm01", mood="calm")
        unplayed_diff = _make_track("aaaa-new0", mood="energetic")
        patches = self._patch_db(
            all_tracks=[current, same_mood_also_recent, unplayed_diff],
            recently_played_ids={"aaaa-cur1", "aaaa-sm01"},  # both calm tracks played recently
            all_played_ids={"aaaa-cur1", "aaaa-sm01"},
        )
        result = self._run_with_patches(
            patches,
            current_track_id="aaaa-cur1",
        )
        assert result is not None
        assert str(result["id"]) == "aaaa-new0"

    def test_tier4_least_recently_played_when_all_played(self):
        t1 = _make_track("aaaa-lrp1")
        t2 = _make_track("aaaa-lrp2")
        lrp = _make_track("aaaa-lrp3", mood="melancholic")
        patches = self._patch_db(
            all_tracks=[t1, t2, lrp],
            recently_played_ids={"aaaa-lrp1", "aaaa-lrp2", "aaaa-lrp3"},
            all_played_ids={"aaaa-lrp1", "aaaa-lrp2", "aaaa-lrp3"},
            least_recent=lrp,
        )
        result = self._run_with_patches(patches)
        assert result is not None
        assert str(result["id"]) == "aaaa-lrp3"

    def test_returns_none_when_no_tracks(self):
        patches = self._patch_db(
            all_tracks=[],
            recently_played_ids=set(),
            all_played_ids=set(),
            least_recent=None,
        )
        result = self._run_with_patches(patches)
        assert result is None

    def test_tier1_all_explicit_played_falls_through_to_tier2(self):
        """If all items in explicit_queue were recently played, fall through to tier 2."""
        current = _make_track("aaaa-c001", mood="uplifting")
        t_explicit = _make_track("aaaa-e001", mood="uplifting")
        t_other = _make_track("aaaa-o001", mood="uplifting")
        patches = self._patch_db(
            all_tracks=[current, t_explicit, t_other],
            recently_played_ids={"aaaa-c001", "aaaa-e001"},  # explicit was played
        )
        result = self._run_with_patches(
            patches,
            current_track_id="aaaa-c001",
            explicit_queue=["aaaa-e001"],  # only entry, already played
        )
        # Falls through to tier 2: same mood (uplifting), t_other not played
        assert result is not None
        assert str(result["id"]) == "aaaa-o001"


# ── Playlist auto-grouping ─────────────────────────────────────────────────────

class TestAutoGroupPlaylists:
    """Test the mood-based auto-grouping logic (pure Python, no DB)."""

    def test_creates_mood_playlist_for_each_mood(self):
        user_id = str(uuid.uuid4())
        upserted = []
        added = []

        def fake_upsert(*, playlist_id, user_id, title, dominant_mood, art_s3_key=None, is_auto_generated=False):
            upserted.append({"id": playlist_id, "mood": dominant_mood, "title": title})

        def fake_add(playlist_id, track_ids, *, user_id):
            added.append({"playlist_id": playlist_id, "track_ids": track_ids})

        from private_internet.content.aria import generator as gen_module

        with patch.object(gen_module, "upsert_playlist", side_effect=fake_upsert), \
             patch.object(gen_module, "add_tracks_to_playlist", side_effect=fake_add):
            gen_module._auto_group_playlists(
                {
                    "calm": ["t-calm-1", "t-calm-2"],
                    "focus": ["t-focus-1"],
                },
                user_id,
            )

        mood_playlists = [u for u in upserted if u["mood"] is not None]
        moods_created = {p["mood"] for p in mood_playlists}
        assert "calm" in moods_created
        assert "focus" in moods_created

        # "From your brain" catch-all also created (dominant_mood=None).
        brain_playlists = [u for u in upserted if u["mood"] is None]
        assert len(brain_playlists) == 1
        assert "brain" in brain_playlists[0]["title"].lower() or "Brain" in brain_playlists[0]["title"]

    def test_brain_playlist_contains_all_tracks(self):
        user_id = str(uuid.uuid4())
        added = []

        def fake_upsert(**_kw):
            pass

        def fake_add(playlist_id, track_ids, *, user_id):
            added.append((playlist_id, list(track_ids)))

        from private_internet.content.aria import generator as gen_module

        with patch.object(gen_module, "upsert_playlist", side_effect=fake_upsert), \
             patch.object(gen_module, "add_tracks_to_playlist", side_effect=fake_add):
            gen_module._auto_group_playlists(
                {"calm": ["t1", "t2"], "energetic": ["t3"]},
                user_id,
            )

        # Collect all track_ids added to each playlist.
        all_added_ids = {tid for _, ids in added for tid in ids}
        assert "t1" in all_added_ids
        assert "t2" in all_added_ids
        assert "t3" in all_added_ids

    def test_empty_mood_dict_creates_nothing(self):
        user_id = str(uuid.uuid4())
        from private_internet.content.aria import generator as gen_module

        with patch.object(gen_module, "upsert_playlist") as mock_upsert, \
             patch.object(gen_module, "add_tracks_to_playlist") as mock_add:
            gen_module._auto_group_playlists({}, user_id)

        mock_upsert.assert_not_called()
        mock_add.assert_not_called()

    def test_mood_playlist_ids_are_deterministic(self):
        """Same user + mood always yields the same playlist_id (idempotent)."""
        user_id = str(uuid.uuid4())
        upserted = []

        def fake_upsert(*, playlist_id, user_id, **kw):
            upserted.append(playlist_id)

        def fake_add(*a, **kw):
            pass

        from private_internet.content.aria import generator as gen_module

        for _ in range(3):
            upserted.clear()
            with patch.object(gen_module, "upsert_playlist", side_effect=fake_upsert), \
                 patch.object(gen_module, "add_tracks_to_playlist", side_effect=fake_add):
                gen_module._auto_group_playlists({"calm": ["t1"]}, user_id)

        # All three runs must produce the same playlist IDs.
        # (we only check that multiple calls produce the same ID, not exact value)
        first_run_ids = upserted
        for _ in range(2):
            upserted2 = []
            with patch.object(gen_module, "upsert_playlist",
                               side_effect=lambda *, playlist_id, user_id, **kw: upserted2.append(playlist_id)), \
                 patch.object(gen_module, "add_tracks_to_playlist", side_effect=lambda *a, **kw: None):
                gen_module._auto_group_playlists({"calm": ["t1"]}, user_id)
            assert set(upserted2) == set(first_run_ids)


# ── Topic-diverse memory sampling ──────────────────────────────────────────────

class TestFetchRecentMemories:
    """The sampler must not let one over-represented theme (e.g. a burst of
    finance memories) dominate the LLM context — that was the 'all songs are
    finance' bug."""

    def _patched_rows(self, rows):
        """Patch generator._connect so _fetch_recent_memories sees `rows`
        (list of dicts) as the recency-window query result."""
        from private_internet.content.aria import generator as gen_module
        cur = MagicMock()
        cur.fetchall.return_value = rows
        conn = MagicMock()
        conn.cursor.return_value = cur
        return patch.object(gen_module, "_connect", return_value=conn)

    def test_diversifies_away_from_dominant_tag(self):
        from private_internet.content.aria import generator as gen_module
        # 50 finance memories, 1 health memory — pure recency would never pick health.
        rows = [{"title": f"f{i}", "content": "c", "tags": "finance"} for i in range(50)]
        rows.append({"title": "h", "content": "c", "tags": "health,daily"})
        with self._patched_rows(rows):
            picked = gen_module._fetch_recent_memories("u" * 36, limit=8)
        titles = {p["title"] for p in picked}
        assert "h" in titles, "health memory must surface despite finance dominance"
        assert len(picked) == 8

    def test_returns_all_when_fewer_than_limit(self):
        from private_internet.content.aria import generator as gen_module
        rows = [{"title": "a", "content": "c", "tags": "x"},
                {"title": "b", "content": "c", "tags": "y"}]
        with self._patched_rows(rows):
            picked = gen_module._fetch_recent_memories("u" * 36, limit=8)
        assert len(picked) == 2

    def test_empty_on_db_error(self):
        from private_internet.content.aria import generator as gen_module
        with patch.object(gen_module, "_connect", side_effect=RuntimeError("boom")):
            assert gen_module._fetch_recent_memories("u" * 36, limit=8) == []
