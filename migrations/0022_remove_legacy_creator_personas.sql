-- 0022_remove_legacy_creator_personas.sql
--
-- Remove the five owner-flavoured legacy creator personas that were seeded
-- during the single-user era (Felix Bergmann, Dr. Layla Nasser, Maksim Volkov,
-- Nora Chen, Viktor Ostrowski). These are global rows (user_id IS NULL) that
-- leaked owner identity into every user's PULSE feed, violating multi-tenancy.
-- The three neutral global defaults (global-science-desk, world-sport-desk,
-- curious-mind) are NOT touched.
--
-- FK order matters: content_posts and content_videos reference content_creators
-- (no ON DELETE CASCADE), so dependent rows must be removed first.
-- content_interactions has no FK (content_id is plain TEXT), so interaction
-- rows that referenced the now-deleted posts/videos go stale — also cleaned up
-- here using the collected post/video ids.
--
-- Idempotent: WHERE + IN guards mean re-running is safe (rows are already gone).
-- Mirrored at API startup in content/db.py::init_content_db().

DO $$
DECLARE
    legacy_slugs TEXT[] := ARRAY[
        'maksim-volkov',
        'dr-layla-nasser',
        'felix-bergmann',
        'nora-chen',
        'viktor-ostrowski'
    ];
    legacy_creator_ids TEXT[];
    legacy_post_ids    TEXT[];
    legacy_video_ids   TEXT[];
BEGIN
    -- Collect the IDs of the legacy global creators (user_id IS NULL guards
    -- against accidentally touching any user-owned persona with the same slug).
    SELECT ARRAY(
        SELECT id FROM content_creators
        WHERE user_id IS NULL AND slug = ANY(legacy_slugs)
    ) INTO legacy_creator_ids;

    IF array_length(legacy_creator_ids, 1) IS NULL THEN
        -- Nothing to do — already cleaned up.
        RETURN;
    END IF;

    -- Collect post IDs that belong to the legacy creators.
    SELECT ARRAY(
        SELECT id FROM content_posts
        WHERE creator_id = ANY(legacy_creator_ids)
    ) INTO legacy_post_ids;

    -- Collect video IDs that belong to the legacy creators.
    SELECT ARRAY(
        SELECT id FROM content_videos
        WHERE creator_id = ANY(legacy_creator_ids)
    ) INTO legacy_video_ids;

    -- Delete interaction rows that reference the orphaned posts or videos.
    IF array_length(legacy_post_ids, 1) IS NOT NULL THEN
        DELETE FROM content_interactions
        WHERE content_type = 'post' AND content_id = ANY(legacy_post_ids);
    END IF;

    IF array_length(legacy_video_ids, 1) IS NOT NULL THEN
        DELETE FROM content_interactions
        WHERE content_type = 'video' AND content_id = ANY(legacy_video_ids);
    END IF;

    -- Delete the posts and videos themselves.
    IF array_length(legacy_post_ids, 1) IS NOT NULL THEN
        DELETE FROM content_posts WHERE creator_id = ANY(legacy_creator_ids);
    END IF;

    IF array_length(legacy_video_ids, 1) IS NOT NULL THEN
        DELETE FROM content_videos WHERE creator_id = ANY(legacy_creator_ids);
    END IF;

    -- Finally, remove the legacy creator rows.
    DELETE FROM content_creators
    WHERE user_id IS NULL AND slug = ANY(legacy_slugs);

END $$;
