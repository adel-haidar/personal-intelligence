"""Bank-link schema bootstrap + row CRUD.

Mirrors migrations/0028_bank_link.sql. Runs idempotently at API startup.

Tables:
  bank_connections        — one row per (user) connected bank
  bank_statement_memories — maps (user, account, month) → brain memory_id

All tables are user-scoped: every row has user_id UUID NOT NULL.  # MUST SCOPE BY USER
"""

from __future__ import annotations

import logging
from datetime import datetime

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect

logger = logging.getLogger(__name__)


def init_bank_link_db() -> None:
    """Create bank-link tables if they don't exist (idempotent)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bank_connections (
                id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id            UUID NOT NULL,
                institution_id     TEXT NOT NULL,
                institution_name   TEXT,
                requisition_id     TEXT NOT NULL,
                account_ids        TEXT[] NOT NULL DEFAULT '{}',
                status             TEXT NOT NULL DEFAULT 'pending',
                consent_expires_at TIMESTAMPTZ,
                last_sync_at       TIMESTAMPTZ,
                last_balance       NUMERIC,
                last_error         TEXT,
                created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_bank_connections_user "
            "ON bank_connections(user_id)"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bank_statement_memories (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id      UUID NOT NULL,
                account_id   TEXT NOT NULL,
                month        TEXT NOT NULL,
                memory_id    TEXT NOT NULL,
                updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, account_id, month)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_bank_statement_memories_user "
            "ON bank_statement_memories(user_id, account_id)"
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── bank_connections CRUD  (all queries scoped by user_id) # MUST SCOPE BY USER ──


def get_connection(user_id: str) -> dict | None:
    """Return the bank_connections row for the user, or None."""
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM bank_connections WHERE user_id = %s",  # MUST SCOPE BY USER
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def upsert_pending_connection(
    user_id: str,
    *,
    institution_id: str,
    institution_name: str | None,
    requisition_id: str,
) -> None:
    """Create/replace a user's bank connection in the 'pending' state.

    Replaces any prior connection (a fresh consent supersedes the old one).
    """
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO bank_connections
                   (user_id, institution_id, institution_name, requisition_id,
                    account_ids, status, updated_at)
               VALUES (%s, %s, %s, %s, '{}', 'pending', now())
               ON CONFLICT (user_id) DO UPDATE SET
                   institution_id   = EXCLUDED.institution_id,
                   institution_name = EXCLUDED.institution_name,
                   requisition_id   = EXCLUDED.requisition_id,
                   account_ids      = '{}',
                   status           = 'pending',
                   consent_expires_at = NULL,
                   last_error       = NULL,
                   updated_at       = now()""",
            (user_id, institution_id, institution_name, requisition_id),  # MUST SCOPE BY USER
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def mark_connected(
    user_id: str,
    *,
    account_ids: list[str],
    consent_expires_at: datetime | None,
    institution_name: str | None = None,
) -> None:
    """Flip a pending connection to 'connected' once consent is granted."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE bank_connections
               SET account_ids = %s,
                   status = 'connected',
                   consent_expires_at = %s,
                   institution_name = COALESCE(%s, institution_name),
                   last_error = NULL,
                   updated_at = now()
               WHERE user_id = %s""",  # MUST SCOPE BY USER
            (account_ids, consent_expires_at, institution_name, user_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def update_sync_result(
    user_id: str,
    *,
    status: str,
    last_balance: float | None = None,
    last_error: str | None = None,
    set_synced_now: bool = False,
) -> None:
    """Record the outcome of a sync (status + optional balance/error/timestamp)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE bank_connections
               SET status = %s,
                   last_balance = COALESCE(%s, last_balance),
                   last_error = %s,
                   last_sync_at = CASE WHEN %s THEN now() ELSE last_sync_at END,
                   updated_at = now()
               WHERE user_id = %s""",  # MUST SCOPE BY USER
            (status, last_balance, last_error, set_synced_now, user_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_connection(user_id: str) -> None:
    """Remove a user's bank connection + its statement-memory map.

    Leaves the brain memories themselves intact (the user's financial history
    should survive a disconnect).
    """
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM bank_connections WHERE user_id = %s",  # MUST SCOPE BY USER
            (user_id,),
        )
        cur.execute(
            "DELETE FROM bank_statement_memories WHERE user_id = %s",  # MUST SCOPE BY USER
            (user_id,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def list_connected_user_ids() -> list[str]:
    """Return user_ids with a 'connected' bank (for the daily poll fan-out)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT user_id FROM bank_connections WHERE status IN ('connected', 'error')"
        )
        return [str(r[0]) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


# ── statement-memory map (per user, account, month)  # MUST SCOPE BY USER ──────


def get_statement_memory_id(user_id: str, account_id: str, month: str) -> str | None:
    """Return the brain memory_id for a (user, account, month), or None."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT memory_id FROM bank_statement_memories
               WHERE user_id = %s AND account_id = %s AND month = %s""",  # MUST SCOPE BY USER
            (user_id, account_id, month),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()
        conn.close()


def upsert_statement_memory_id(
    user_id: str, account_id: str, month: str, memory_id: str
) -> None:
    """Record the brain memory_id holding a (user, account, month) statement."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO bank_statement_memories
                   (user_id, account_id, month, memory_id, updated_at)
               VALUES (%s, %s, %s, %s, now())
               ON CONFLICT (user_id, account_id, month) DO UPDATE SET
                   memory_id = EXCLUDED.memory_id,
                   updated_at = now()""",
            (user_id, account_id, month, memory_id),  # MUST SCOPE BY USER
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
