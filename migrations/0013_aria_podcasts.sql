-- 0013_aria_podcasts.sql
-- ARIA Podcasts: two-host AI podcast episodes generated from brain memory clusters.
-- Idempotent: CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS guards.
-- All user-data tables have user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE.
-- Run at API startup by aria/podcast_db.py::init_aria_podcast_db(); also kept
-- here for the database-agent and manual deploys.

CREATE TABLE IF NOT EXISTS aria_podcasts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title               VARCHAR(255) NOT NULL,
    description         TEXT,
    topic_category      VARCHAR(100),
    duration_seconds    INTEGER,
    status              VARCHAR(20) NOT NULL DEFAULT 'generating',
                        -- status: generating | ready | failed
    audio_s3_key        VARCHAR(500),
    waveform_s3_key     VARCHAR(500),
    art_s3_key          VARCHAR(500),
    transcript          JSONB,          -- full dialogue for display
    brain_topic_ids     UUID[],
    host_a_name         VARCHAR(100) NOT NULL DEFAULT 'Alex',
    host_b_name         VARCHAR(100) NOT NULL DEFAULT 'Jordan',
    language_code       VARCHAR(10) NOT NULL DEFAULT 'en',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_aria_podcasts_user
    ON aria_podcasts (user_id, created_at DESC);

-- Likes, mirroring aria_liked_tracks so podcasts reuse the player like-button.
CREATE TABLE IF NOT EXISTS aria_liked_podcasts (
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    podcast_id  UUID NOT NULL REFERENCES aria_podcasts(id) ON DELETE CASCADE,
    liked_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, podcast_id)
);
CREATE INDEX IF NOT EXISTS idx_aria_liked_podcasts_user
    ON aria_liked_podcasts (user_id, liked_at DESC);
