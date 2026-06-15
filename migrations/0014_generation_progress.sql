-- 0014_generation_progress.sql
-- Scene-stitching long-form video pipeline (SIGNAL + STORIES).
-- Tracks per-clip generation progress so the frontend can show a progress bar
-- while a multi-minute video assembles from many short clips.
--
-- Progress JSON structure:
-- {
--   "total_scenes": 45,
--   "clips_generated": 12,
--   "narration_ready": false,
--   "assembly_started": false,
--   "current_stage": "generating_clips"
-- }
--
-- Mirrored idempotently at API startup (content/db.py + stories/db.py).
-- Idempotent — safe to run at every API startup.

ALTER TABLE content_videos ADD COLUMN IF NOT EXISTS generation_progress JSONB DEFAULT '{}';
ALTER TABLE stories_films  ADD COLUMN IF NOT EXISTS generation_progress JSONB DEFAULT '{}';
