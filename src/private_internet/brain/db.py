"""Brain Organiser schema bootstrap.

Mirrors migrations/0008_brain_organise.sql. Runs idempotently at API startup
(the repo's bootstrap-at-startup convention, like core/saas_migration.py).

Adds:
  - memories.merged_into  (soft-delete pointer; NULL = active memory)
  - brain_organise_runs   (one row per organise run, per user)

Never drops or alters existing columns. memories.memory_id is TEXT, so
merged_into is TEXT (a memory_id), not UUID.
"""

import logging

from private_internet.database import _connect

logger = logging.getLogger(__name__)


def init_brain_db() -> None:
    conn = _connect()
    cur = conn.cursor()
    try:
        # Soft-delete pointer: a merged source memory points at the new memory.
        cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS merged_into TEXT")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_merged_into ON memories(merged_into)"
        )

        cur.execute("""
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
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_brain_runs_user_started "
            "ON brain_organise_runs(user_id, started_at DESC)"
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
