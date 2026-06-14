"""User accounts for the multi-tenant Private Internet platform."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
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
    # SaaS columns referenced by create_user. The full SaaS migration
    # (core/saas_migration.py) runs later in lifespan and (re)asserts these
    # idempotently plus the rest; we add the two that create_user writes here so
    # seed-admin creation during the earlier multi-tenancy step does not fail on
    # a fresh database.
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(32) DEFAULT 'free'")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS registration_ip VARCHAR(64)")
    conn.commit()
    cur.close()
    conn.close()


# Sensitive/secret columns that must never be serialized into an API response.
_PRIVATE_COLUMNS = (
    "password_hash",
    "email_verification_token",
    "password_reset_token",
)


def _serialize_user(row: dict) -> dict:
    user = dict(row)
    user["id"] = str(user["id"])
    for key, value in list(user.items()):
        if isinstance(value, datetime):
            user[key] = value.isoformat()
    for col in _PRIVATE_COLUMNS:
        user.pop(col, None)  # secrets never leak past the service layer
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
    plan: str = "free",
    registration_ip: str | None = None,
) -> dict:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """INSERT INTO users (email, display_name, password_hash, is_admin, plan, registration_ip)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (email, display_name, password_hash, is_admin, plan, registration_ip),
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
        "plan", "email_verified", "provisioned_at",
        "email_verification_token", "email_verification_sent_at",
        "password_reset_token", "password_reset_expires_at",
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


# ── Billing / subscriptions ─────────────────────────────────────────

def get_user_by_stripe_customer_id(customer_id: str) -> dict | None:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE stripe_customer_id = %s", (customer_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return _serialize_user(row) if row else None


def set_stripe_customer_id(user_id: str, customer_id: str) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET stripe_customer_id = %s WHERE id = %s",
        (customer_id, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def set_subscription(
    user_id: str,
    *,
    status: str,
    stripe_subscription_id: str | None = None,
    current_period_end=None,
) -> None:
    """Update a user's subscription state (called from the Stripe webhook)."""
    sets = ["subscription_status = %s"]
    params: list = [status]
    if stripe_subscription_id is not None:
        sets.append("stripe_subscription_id = %s")
        params.append(stripe_subscription_id)
    if current_period_end is not None:
        sets.append("subscription_current_period_end = %s")
        params.append(current_period_end)
    params.append(user_id)
    conn = _connect()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", tuple(params))
    conn.commit()
    cur.close()
    conn.close()


# ── Email verification ──────────────────────────────────────────────

def set_verification_token(user_id: str) -> str:
    """Generate, store and return a fresh email-verification token."""
    token = secrets.token_urlsafe(32)
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """UPDATE users
           SET email_verification_token = %s, email_verification_sent_at = %s
           WHERE id = %s""",
        (token, datetime.now(timezone.utc), user_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return token


def get_user_by_verification_token(token: str) -> dict | None:
    """Return the (unverified) user holding this verification token, if any.

    The returned dict includes ``email_verification_sent_at`` (ISO string) so the
    caller can enforce the TTL. Never returns already-verified users.
    """
    if not token:
        return None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """SELECT * FROM users
           WHERE email_verification_token = %s AND email_verified = FALSE""",
        (token,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return _serialize_user(row) if row else None


def mark_email_verified(user_id: str) -> dict | None:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """UPDATE users
           SET email_verified = TRUE,
               email_verification_token = NULL,
               email_verification_sent_at = NULL
           WHERE id = %s
           RETURNING *""",
        (user_id,),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return _serialize_user(row) if row else None


# ── Password reset ──────────────────────────────────────────────────

def set_reset_token(user_id: str, ttl_hours: int) -> str:
    """Generate, store and return a password-reset token with an expiry."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """UPDATE users
           SET password_reset_token = %s, password_reset_expires_at = %s
           WHERE id = %s""",
        (token, expires, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return token


def get_user_by_reset_token(token: str) -> dict | None:
    """Return the user holding this reset token (regardless of expiry — the
    caller decides). Includes ``password_reset_expires_at`` (ISO string)."""
    if not token:
        return None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE password_reset_token = %s", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return _serialize_user(row) if row else None


def clear_reset_token(user_id: str) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """UPDATE users
           SET password_reset_token = NULL, password_reset_expires_at = NULL
           WHERE id = %s""",
        (user_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def set_password(user_id: str, password_hash: str) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (password_hash, user_id),
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


# ── Account deletion ─────────────────────────────────────────────────

# Every user-scoped table. content_creators / plan_limits are shared (no user_id).
# Ordered children-before-parents so FK constraints never block the delete.
_USER_DATA_TABLES = [
    "content_interactions",
    "content_research",
    "content_posts",
    "content_videos",
    "content_topics",
    "user_creator_preferences",
    "health_metrics",
    "job_matches",
    "memories",
]


def delete_account(user_id: str) -> None:
    """Permanently delete a user and ALL their data from this server.

    Skips tables that don't exist in this deployment (to_regclass guard) so it
    works whether or not the agents' health/job tables share the database.
    """
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        for table in _USER_DATA_TABLES:
            cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
            if cur.fetchone()[0] is None:
                continue
            cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        logger.info(f"[user:{user_id[:8]}] account and all data deleted")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


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
