"""SaaS migration: user verification/reset/plan columns + provisioning tables.

Runs idempotently at startup AFTER migrate_multi_tenancy (the repo's
bootstrap-at-startup convention). Mirrors:
  - migrations/0006_saas_users.sql
  - migrations/0007_user_provisioning.sql

Row Level Security is intentionally NOT enabled. database.py::_connect opens a
fresh connection per query and never sets a session GUC, so session-scoped RLS
would silently break every query. Tenant isolation stays in application code via
the `WHERE user_id = ctx.user_id` convention.

content_creators.id is TEXT (see content/db.py), so user_creator_preferences
references it as TEXT, not UUID.
"""

import logging

from private_internet.database import _connect

logger = logging.getLogger(__name__)

_USER_COLUMNS = [
    ("email_verified", "BOOLEAN DEFAULT FALSE"),
    ("email_verification_token", "VARCHAR(128)"),
    ("email_verification_sent_at", "TIMESTAMPTZ"),
    ("password_reset_token", "VARCHAR(128)"),
    ("password_reset_expires_at", "TIMESTAMPTZ"),
    ("plan", "VARCHAR(32) DEFAULT 'free'"),
    ("plan_expires_at", "TIMESTAMPTZ"),
    ("registration_ip", "VARCHAR(64)"),
    ("provisioned_at", "TIMESTAMPTZ"),
]

# plan → (max_memories, max_posts_per_week, max_videos_per_week,
#         max_storage_mb, content_generation_enabled). NULL = unlimited.
_PLAN_LIMITS = [
    ("free", 500, 10, 2, 1024, True),
    ("personal", 5000, 50, 10, 10240, True),
    ("pro", None, None, None, 102400, True),
]


def migrate_saas() -> None:
    conn = _connect()
    cur = conn.cursor()
    try:
        # ── 0006: SaaS columns on users ──────────────────────────────
        for name, ddl in _USER_COLUMNS:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {ddl}")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email_verification_token "
            "ON users(email_verification_token)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_password_reset_token "
            "ON users(password_reset_token)"
        )

        # ── 0006: plan_limits ────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plan_limits (
                plan VARCHAR(32) PRIMARY KEY,
                max_memories INT,
                max_posts_per_week INT,
                max_videos_per_week INT,
                max_storage_mb INT,
                content_generation_enabled BOOLEAN DEFAULT TRUE
            )
        """)
        for row in _PLAN_LIMITS:
            cur.execute(
                """INSERT INTO plan_limits
                   (plan, max_memories, max_posts_per_week, max_videos_per_week,
                    max_storage_mb, content_generation_enabled)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (plan) DO NOTHING""",
                row,
            )

        # ── 0007: user_creator_preferences ───────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_creator_preferences (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                creator_id TEXT NOT NULL REFERENCES content_creators(id) ON DELETE CASCADE,
                weight FLOAT DEFAULT 1.0,
                is_enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE (user_id, creator_id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_creator_prefs_user "
            "ON user_creator_preferences(user_id)"
        )

        conn.commit()
        logger.info("SaaS migration applied (user columns, plan_limits, user_creator_preferences)")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
