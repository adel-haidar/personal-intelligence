-- 0008_brain_organise.sql
-- Brain Organiser: soft-delete pointer on memories + run-log table.
-- Mirrored idempotently at startup by src/private_internet/brain/db.py::init_brain_db.
-- Does NOT drop or alter any existing column.

ALTER TABLE memories ADD COLUMN IF NOT EXISTS merged_into TEXT;
CREATE INDEX IF NOT EXISTS idx_memories_merged_into ON memories(merged_into);

CREATE TABLE IF NOT EXISTS brain_organise_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    memories_before INT,
    memories_after INT,
    duplicates_removed INT,
    clusters_merged INT,
    status VARCHAR(16) NOT NULL DEFAULT 'running'
);
CREATE INDEX IF NOT EXISTS idx_brain_runs_user_started
    ON brain_organise_runs(user_id, started_at DESC);
