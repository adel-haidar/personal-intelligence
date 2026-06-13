"""User accounts for the multi-tenant Private Internet platform."""

import logging
from datetime import datetime, timezone
from functools import lru_cache

from psycopg2.extras import RealDictCursor

from private_internet.config import get_settings
from private_internet.database import _connect

logger = logging.getLogger(__name__)


def init_users_db() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(256) UNIQUE NOT NULL,
            display_name VARCHAR(128),
            avatar_url TEXT,
            password_hash TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            language_preference VARCHAR(16) DEFAULT 'en',
            onboarding_completed BOOLEAN DEFAULT FALSE,
            onboarding_step INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            last_active_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def _serialize_user(row: dict) -> dict:
    user = dict(row)
    user["id"] = str(user["id"])
    for key in ("created_at", "last_active_at"):
        if isinstance(user.get(key), datetime):
            user[key] = user[key].isoformat()
    user.pop("password_hash", None)  # never leaks past the service layer
    return user


def get_user_by_email(email: str, include_password_hash: bool = False) -> dict | None:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE lower(email) = lower(%s)", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        return None
    password_hash = row.get("password_hash")
    user = _serialize_user(row)
    if include_password_hash:
        user["password_hash"] = password_hash
    return user


def get_user_by_id(user_id: str) -> dict | None:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return _serialize_user(row) if row else None


def count_users() -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total


def create_user(
    email: str,
    display_name: str,
    password_hash: str | None = None,
    is_admin: bool = False,
) -> dict:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """INSERT INTO users (email, display_name, password_hash, is_admin)
           VALUES (%s, %s, %s, %s)
           RETURNING *""",
        (email, display_name, password_hash, is_admin),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"[user:{str(row['id'])[:8]}] User created: {email}")
    return _serialize_user(row)


def update_user(user_id: str, **fields) -> dict | None:
    """Update whitelisted profile/onboarding fields."""
    allowed = {
        "display_name", "avatar_url", "password_hash", "language_preference",
        "onboarding_completed", "onboarding_step", "is_admin",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user_by_id(user_id)

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        f"UPDATE users SET {set_clause} WHERE id = %s RETURNING *",
        (*updates.values(), user_id),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return _serialize_user(row) if row else None


def touch_last_active(user_id: str) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET last_active_at = %s WHERE id = %s",
        (datetime.now(timezone.utc), user_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def list_onboarded_user_ids() -> list[str]:
    """Users whose pipelines should run in scheduled jobs."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE onboarding_completed = TRUE ORDER BY created_at")
    ids = [str(r[0]) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return ids


def _seed_admin_email() -> str:
    settings = get_settings()
    return settings.seed_admin_email or f"admin@{settings.app_domain}"


def ensure_seed_admin() -> str:
    """
    Create the seed admin account if missing and return its user id.
    All pre-multi-tenancy data is assigned to this user, and legacy
    OAuth/MCP tokens (claude.ai) resolve to this user.
    """
    email = _seed_admin_email()
    user = get_user_by_email(email)
    if user is None:
        user = create_user(
            email=email,
            display_name=email.split("@")[0],
            is_admin=True,
        )
        # The seed admin owns the pre-existing brain — onboarding is moot.
        update_user(user["id"], onboarding_completed=True)
        logger.info(f"Seed admin created: {email}")
    return user["id"]


@lru_cache(maxsize=1)
def get_seed_admin_id() -> str:
    """Cached seed admin id — stable for the process lifetime."""
    return ensure_seed_admin()
