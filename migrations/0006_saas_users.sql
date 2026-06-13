-- 0006_saas_users.sql — Private Internet SaaS user columns + plan limits
--
-- NOTE: This migration also runs automatically and idempotently at API startup
-- (src/private_internet/core/saas_migration.py::migrate_saas). This file
-- documents it for manual / disaster-recovery use. Run with:
--
--   psql "$DATABASE_URL" -f 0006_saas_users.sql
--
-- Row Level Security is INTENTIONALLY NOT enabled here. The application opens a
-- fresh psycopg2 connection per query (database.py::_connect) and never sets a
-- session GUC, so session-scoped RLS policies would silently break every query.
-- Tenant isolation is enforced in application code via the
-- `WHERE user_id = ctx.user_id` convention (see core/request_context.py). RLS is
-- deferred until the data layer adopts a connection-pool + session-var model.

BEGIN;

-- ── SaaS columns on users (is_admin / last_active_at already exist) ──
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_sent_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(32) DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS registration_ip VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS provisioned_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_email_verification_token
    ON users(email_verification_token);
CREATE INDEX IF NOT EXISTS idx_users_password_reset_token
    ON users(password_reset_token);

-- ── plan_limits (NULL == unlimited) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS plan_limits (
    plan VARCHAR(32) PRIMARY KEY,
    max_memories INT,                 -- NULL = unlimited
    max_posts_per_week INT,           -- NULL = unlimited
    max_videos_per_week INT,          -- NULL = unlimited
    max_storage_mb INT,
    content_generation_enabled BOOLEAN DEFAULT TRUE
);

INSERT INTO plan_limits
    (plan, max_memories, max_posts_per_week, max_videos_per_week, max_storage_mb, content_generation_enabled)
VALUES
    ('free',     500,  10,  2,   1024,  TRUE),
    ('personal', 5000, 50,  10,  10240, TRUE),
    ('pro',      NULL, NULL, NULL, 102400, TRUE)
ON CONFLICT (plan) DO NOTHING;

COMMIT;
