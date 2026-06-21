-- 0025_connectors.sql
-- External-platform connector tables (Notion, GitHub, Google Drive, …).
-- Mirrors connectors/db.py::init_connectors_db() which runs this idempotently
-- at API startup.
--
-- Multi-tenancy: every row has user_id UUID NOT NULL.  # MUST SCOPE BY USER
-- connector_accounts has UNIQUE(user_id, connector_id) — one connection per
-- (user, platform). connector_items deduplicates imported documents so re-syncs
-- upsert rather than create duplicate embeddings.

-- One row per connected OAuth account.
CREATE TABLE IF NOT EXISTS connector_accounts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    connector_id     TEXT NOT NULL,
    access_token     TEXT NOT NULL,
    refresh_token    TEXT,
    expiry           TIMESTAMPTZ,
    scopes           TEXT,
    external_account TEXT,                         -- e.g. "adel@gmail.com" or GitHub login
    status           TEXT NOT NULL DEFAULT 'connected', -- 'connected' | 'syncing' | 'error'
    last_sync_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, connector_id)
);

CREATE INDEX IF NOT EXISTS idx_connector_accounts_user
    ON connector_accounts(user_id);

-- One row per successfully imported document (deduplicate on re-sync).
CREATE TABLE IF NOT EXISTS connector_items (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    connector_id TEXT NOT NULL,
    external_id  TEXT NOT NULL,                    -- provider-issued document id
    memory_id    TEXT,                             -- brain memory_id (TEXT, not UUID)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, connector_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_connector_items_user
    ON connector_items(user_id, connector_id);
