-- 0016_oauth_user_binding.sql
-- Bind each OAuth authorization (code) and issued token to the platform user
-- who authorized it, so the MCP memory server can scope to the REAL connecting
-- user instead of always the seed admin.
--
-- Idempotent: safe to re-run. Mirrored by the startup bootstrap in
-- auth/oauth.py::create_oauth_tables() so a fresh database gets these columns
-- without a manual migration step.
--
-- Backfill: every PRE-EXISTING code/token is assigned to the seed admin, so any
-- claude.ai session that is already connected keeps resolving to the owner's
-- brain until it re-authorizes. New authorizations bind to their real user.

BEGIN;

ALTER TABLE oauth_codes  ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS user_id UUID;

-- FK to users(id). Guard with a catalog check so re-runs don't error, and so a
-- deployment whose `users` table has not been created yet does not fail hard
-- (the multi-tenancy step creates `users` before auth bootstrap on a fresh DB).
DO $$
BEGIN
    IF to_regclass('public.users') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'oauth_codes_user_id_fkey'
        ) THEN
            ALTER TABLE oauth_codes
                ADD CONSTRAINT oauth_codes_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'oauth_tokens_user_id_fkey'
        ) THEN
            ALTER TABLE oauth_tokens
                ADD CONSTRAINT oauth_tokens_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        END IF;

        -- Backfill legacy rows (user_id IS NULL) to the seed admin so currently
        -- connected claude.ai sessions keep working as the owner.
        UPDATE oauth_codes  c
           SET user_id = a.id
          FROM (SELECT id FROM users WHERE is_admin = TRUE ORDER BY created_at LIMIT 1) a
         WHERE c.user_id IS NULL;

        UPDATE oauth_tokens t
           SET user_id = a.id
          FROM (SELECT id FROM users WHERE is_admin = TRUE ORDER BY created_at LIMIT 1) a
         WHERE t.user_id IS NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_oauth_tokens_user_id ON oauth_tokens(user_id);

COMMIT;
