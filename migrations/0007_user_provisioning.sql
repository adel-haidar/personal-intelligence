-- 0007_user_provisioning.sql — per-user content creator preferences
--
-- NOTE: This migration also runs automatically and idempotently at API startup
-- (src/private_internet/core/saas_migration.py::migrate_saas). This file
-- documents it for manual / disaster-recovery use. Run with:
--
--   psql "$DATABASE_URL" -f 0007_user_provisioning.sql
--
-- content_creators is a SHARED platform table (no user_id). This join table
-- records which shared creators a given user is subscribed to, with a per-user
-- weight, so provisioning can seed a personalised content feed.

BEGIN;

CREATE TABLE IF NOT EXISTS user_creator_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    creator_id TEXT NOT NULL REFERENCES content_creators(id) ON DELETE CASCADE,
    weight FLOAT DEFAULT 1.0,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, creator_id)
);

CREATE INDEX IF NOT EXISTS idx_user_creator_prefs_user
    ON user_creator_preferences(user_id);

COMMIT;
