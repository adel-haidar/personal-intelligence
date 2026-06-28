-- 0028_bank_link.sql
-- Bank-account linking via GoCardless Bank Account Data (PSD2 AISP).
-- Mirrors bank_link/db.py::init_bank_link_db() which runs this idempotently
-- at API startup.
--
-- We store NO bank credentials/PIN: GoCardless holds the consent. Per user we
-- keep only a requisition id + the account ids it granted. Daily polling renders
-- each account's month into a statement-shaped brain memory the existing
-- BankAdviser already understands.
--
-- Multi-tenancy: every row has user_id UUID NOT NULL.  # MUST SCOPE BY USER

-- One row per connected bank (v1: one bank per user → UNIQUE(user_id)).
CREATE TABLE IF NOT EXISTS bank_connections (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL,
    institution_id     TEXT NOT NULL,                 -- GoCardless institution id, e.g. SPARKASSE_…
    institution_name   TEXT,                          -- human label, e.g. "Sparkasse Köln Bonn"
    requisition_id     TEXT NOT NULL,                 -- GoCardless requisition id
    account_ids        TEXT[] NOT NULL DEFAULT '{}',  -- GoCardless account ids granted by consent
    status             TEXT NOT NULL DEFAULT 'pending',-- 'pending'|'connected'|'error'|'expired'
    consent_expires_at TIMESTAMPTZ,                   -- PSD2 SCA expiry (re-consent needed after)
    last_sync_at       TIMESTAMPTZ,
    last_balance       NUMERIC,                       -- latest known balance (display only)
    last_error         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_bank_connections_user
    ON bank_connections(user_id);

-- Maps (user, account, month) → the brain memory_id holding that month's
-- statement, so the daily poll UPDATES one memory per month (the month grows)
-- instead of accumulating duplicates.
CREATE TABLE IF NOT EXISTS bank_statement_memories (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    account_id   TEXT NOT NULL,                       -- GoCardless account id
    month        TEXT NOT NULL,                       -- 'YYYY-MM'
    memory_id    TEXT NOT NULL,                       -- brain memory_id (TEXT, not UUID)
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, account_id, month)
);

CREATE INDEX IF NOT EXISTS idx_bank_statement_memories_user
    ON bank_statement_memories(user_id, account_id);
