-- 0019_aria_playlist_dedupe.sql
-- ARIA auto-generated playlists were keyed by a deterministic id,
-- uuid5(f"{user_id}:mood:{mood}"). That only dedupes within a *single stable*
-- user_id. When the resolved user changed across runs (seed-admin vs platform
-- user binding — see 0016_oauth_user_binding.sql), the same logical playlist
-- ("Deep Focus", "From Your Brain", …) was created twice with different ids,
-- so the library showed duplicate cards.
--
-- This migration:
--   1. Merges duplicate auto-generated playlists per (user_id, dominant_mood),
--      keeping the earliest row, repointing its tracks, deleting the rest.
--      A NULL dominant_mood is the single "From Your Brain" catch-all.
--   2. Recomputes track_count / total_duration on the survivors.
--   3. Adds a NULLS-NOT-DISTINCT partial unique index (PostgreSQL 15+) so the
--      duplication cannot recur even if the resolved user_id changes again.
--
-- Idempotent: safe to re-run. Mirrored by the startup bootstrap in
-- content/aria/db.py::dedupe_auto_playlists().

BEGIN;

CREATE TEMP TABLE _aria_pl_dupes ON COMMIT DROP AS
SELECT id,
       FIRST_VALUE(id) OVER (
           PARTITION BY user_id, COALESCE(dominant_mood::text, '__brain__')
           ORDER BY created_at, id
       ) AS keep_id
FROM aria_playlists
WHERE is_auto_generated = TRUE;

-- Repoint tracks from duplicates onto the surviving playlist.
INSERT INTO aria_playlist_tracks (playlist_id, track_id, position)
SELECT d.keep_id, pt.track_id, pt.position
FROM aria_playlist_tracks pt
JOIN _aria_pl_dupes d ON d.id = pt.playlist_id
WHERE d.id <> d.keep_id
ON CONFLICT (playlist_id, track_id) DO NOTHING;

DELETE FROM aria_playlist_tracks
WHERE playlist_id IN (SELECT id FROM _aria_pl_dupes WHERE id <> keep_id);

DELETE FROM aria_playlists
WHERE id IN (SELECT id FROM _aria_pl_dupes WHERE id <> keep_id);

-- Recompute counts on the survivors.
UPDATE aria_playlists p
SET track_count    = COALESCE(sub.cnt, 0),
    total_duration = COALESCE(sub.dur, 0),
    updated_at     = now()
FROM (
    SELECT pt.playlist_id,
           COUNT(*)                              AS cnt,
           COALESCE(SUM(t.duration_seconds), 0)  AS dur
    FROM aria_playlist_tracks pt
    JOIN aria_tracks t ON t.id = pt.track_id
    GROUP BY pt.playlist_id
) sub
WHERE p.id = sub.playlist_id AND p.is_auto_generated = TRUE;

COMMIT;

-- Prevent recurrence: one auto-generated playlist per (user_id, dominant_mood);
-- NULLS NOT DISTINCT collapses the single NULL-mood "From Your Brain" row too.
CREATE UNIQUE INDEX IF NOT EXISTS uq_aria_playlists_auto_natural
ON aria_playlists (user_id, dominant_mood) NULLS NOT DISTINCT
WHERE is_auto_generated;
