"""Multi-tenancy migration: user_id on every user-data table.

Runs idempotently at startup (the repo's bootstrap-at-startup convention).
migrations/0005_multi_tenancy.sql documents the same migration for manual use.

Tables with `default_admin=True` receive a column DEFAULT of the seed admin's
id because external writers (the agents service for health/job data, the
claude.ai MCP connector for memories) do not send a user_id. Their writes are
intentionally admin-scoped. Content tables get NO default: the generation jobs
must pass user_id explicitly and assert on it.

content_creators is deliberately absent — creators are shared platform personas.
"""

import logging

from private_internet.database import _connect
from private_internet.users.service import ensure_seed_admin, init_users_db

logger = logging.getLogger(__name__)

# table name → whether external (non-platform) writers need an admin default
_TENANT_TABLES = {
    "memories": {"default_admin": True},
    "content_posts": {"default_admin": False},
    "content_videos": {"default_admin": False},
    "content_topics": {"default_admin": False},
    "content_research": {"default_admin": False},
    "content_interactions": {"default_admin": False},
    "health_metrics": {"default_admin": True},   # written by the agents service
    "job_matches": {"default_admin": True},      # written by the agents service
}


def migrate_multi_tenancy() -> None:
    init_users_db()
    admin_id = ensure_seed_admin()

    conn = _connect()
    cur = conn.cursor()
    try:
        for table, opts in _TENANT_TABLES.items():
            cur.execute("SELECT to_regclass(%s)", (table,))
            if cur.fetchone()[0] is None:
                continue  # table owned by a service that hasn't bootstrapped yet

            cur.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)"
            )
            # Backfill all pre-multi-tenancy rows to the seed admin
            cur.execute(f"UPDATE {table} SET user_id = %s WHERE user_id IS NULL", (admin_id,))
            if opts["default_admin"]:
                cur.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET DEFAULT %s", (admin_id,))
            cur.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL")
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)")

        # Topic slugs were globally unique; with tenancy they are unique per user.
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'content_topics_slug_key') THEN
                    ALTER TABLE content_topics DROP CONSTRAINT content_topics_slug_key;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'content_topics_user_slug_key') THEN
                    ALTER TABLE content_topics
                        ADD CONSTRAINT content_topics_user_slug_key UNIQUE (user_id, slug);
                END IF;
            END $$;
        """)

        conn.commit()
        logger.info("Multi-tenancy migration applied (seed admin %s…)", admin_id[:8])
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
