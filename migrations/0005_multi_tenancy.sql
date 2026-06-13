-- 0005_multi_tenancy.sql — Private Internet multi-user migration
--
-- NOTE: This migration also runs automatically and idempotently at API startup
-- (src/private_internet/core/tenancy.py). This file documents it for manual /
-- disaster-recovery use. Run with:
--
--   psql "$DATABASE_URL" -v seed_admin_email="'admin@your-domain.com'" -f 0005_multi_tenancy.sql

BEGIN;

-- ── Users ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(256) UNIQUE NOT NULL,
    display_name VARCHAR(128),
    avatar_url TEXT,
    password_hash TEXT,
    is_admin BOOLEAN DEFAULT FALSE,
    language_preference VARCHAR(16) DEFAULT 'en',
    onboarding_completed BOOLEAN DEFAULT FALSE,
    onboarding_step INT DEFAULT 0,           -- tracks which onboarding step they're on
    created_at TIMESTAMPTZ DEFAULT now(),
    last_active_at TIMESTAMPTZ DEFAULT now()
);

-- Seed admin: existing single-user data is assigned to this account.
INSERT INTO users (email, display_name, is_admin, onboarding_completed)
VALUES (:seed_admin_email, split_part(:seed_admin_email, '@', 1), TRUE, TRUE)
ON CONFLICT (email) DO NOTHING;

-- ── user_id on every user-data table ─────────────────────────────
-- content_creators is deliberately NOT here: creators are shared platform personas.
DO $$
DECLARE
    admin_id UUID;
    t TEXT;
    -- tables written by external services (agents, claude.ai MCP) keep an
    -- admin DEFAULT so their writes stay admin-scoped without code changes
    tables_with_default TEXT[] := ARRAY['memories', 'health_metrics', 'job_matches'];
    tables_strict TEXT[] := ARRAY['content_posts', 'content_videos', 'content_topics',
                                  'content_research', 'content_interactions'];
BEGIN
    SELECT id INTO admin_id FROM users WHERE email = :seed_admin_email;

    FOREACH t IN ARRAY tables_with_default || tables_strict LOOP
        IF to_regclass(t) IS NULL THEN CONTINUE; END IF;
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)', t);
        EXECUTE format('UPDATE %I SET user_id = $1 WHERE user_id IS NULL', t) USING admin_id;
        IF t = ANY(tables_with_default) THEN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN user_id SET DEFAULT %L', t, admin_id);
        END IF;
        EXECUTE format('ALTER TABLE %I ALTER COLUMN user_id SET NOT NULL', t);
        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_user ON %I(user_id)', t, t);
    END LOOP;
END $$;

-- ── Topic slugs: globally unique → unique per user ────────────────
ALTER TABLE content_topics DROP CONSTRAINT IF EXISTS content_topics_slug_key;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'content_topics_user_slug_key') THEN
        ALTER TABLE content_topics ADD CONSTRAINT content_topics_user_slug_key UNIQUE (user_id, slug);
    END IF;
END $$;

COMMIT;
