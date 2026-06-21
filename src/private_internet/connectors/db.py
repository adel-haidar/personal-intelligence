"""Connectors schema bootstrap.

Mirrors migrations/0025_connectors.sql. Runs idempotently at API startup.

Tables:
  connector_accounts  — one row per (user, connector) OAuth connection
  connector_items     — one row per imported item (for deduplication)

All tables are user-scoped: every row has user_id UUID NOT NULL.  # MUST SCOPE BY USER
"""

from __future__ import annotations

import logging
from datetime import datetime

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect

logger = logging.getLogger(__name__)


def init_connectors_db() -> None:
    """Create connector tables if they don't exist (idempotent)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS connector_accounts (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id         UUID NOT NULL,
                connector_id    TEXT NOT NULL,
                access_token    TEXT NOT NULL,
                refresh_token   TEXT,
                expiry          TIMESTAMPTZ,
                scopes          TEXT,
                external_account TEXT,
                status          TEXT NOT NULL DEFAULT 'connected',
                last_sync_at    TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, connector_id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_connector_accounts_user "
            "ON connector_accounts(user_id)"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS connector_items (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id         UUID NOT NULL,
                connector_id    TEXT NOT NULL,
                external_id     TEXT NOT NULL,
                memory_id       TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, connector_id, external_id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_connector_items_user "
            "ON connector_items(user_id, connector_id)"
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Token storage helpers  (all queries scoped by user_id) # MUST SCOPE BY USER ──


def get_account(connector_id: str, user_id: str) -> dict | None:
    """Return the connector_accounts row for (user_id, connector_id), or None."""
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM connector_accounts WHERE user_id = %s AND connector_id = %s",
            (user_id, connector_id),  # MUST SCOPE BY USER
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def get_all_accounts(user_id: str) -> dict[str, dict]:
    """Return all connector_accounts rows for the user keyed by connector_id."""
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM connector_accounts WHERE user_id = %s",  # MUST SCOPE BY USER
            (user_id,),
        )
        rows = cur.fetchall()
        return {row["connector_id"]: dict(row) for row in rows}
    finally:
        cur.close()
        conn.close()


def save_account(
    connector_id: str,
    user_id: str,
    *,
    access_token: str,
    refresh_token: str | None,
    expiry: datetime | None,
    scopes: str | None,
    external_account: str | None,
    status: str = "connected",
) -> None:
    """Upsert a connector_accounts row for (user_id, connector_id)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO connector_accounts
                   (user_id, connector_id, access_token, refresh_token, expiry,
                    scopes, external_account, status, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (user_id, connector_id) DO UPDATE SET
                   access_token     = EXCLUDED.access_token,
                   refresh_token    = EXCLUDED.refresh_token,
                   expiry           = EXCLUDED.expiry,
                   scopes           = EXCLUDED.scopes,
                   external_account = EXCLUDED.external_account,
                   status           = EXCLUDED.status,
                   updated_at       = now()""",
            (user_id, connector_id, access_token, refresh_token, expiry,  # MUST SCOPE BY USER
             scopes, external_account, status),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def update_account_status(
    connector_id: str,
    user_id: str,
    *,
    status: str,
    last_sync_at: datetime | None = None,
) -> None:
    """Update status (and optionally last_sync_at) for an existing account."""
    conn = _connect()
    cur = conn.cursor()
    try:
        if last_sync_at is not None:
            cur.execute(
                """UPDATE connector_accounts
                   SET status = %s, last_sync_at = %s, updated_at = now()
                   WHERE user_id = %s AND connector_id = %s""",  # MUST SCOPE BY USER
                (status, last_sync_at, user_id, connector_id),
            )
        else:
            cur.execute(
                """UPDATE connector_accounts
                   SET status = %s, updated_at = now()
                   WHERE user_id = %s AND connector_id = %s""",  # MUST SCOPE BY USER
                (status, user_id, connector_id),
            )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_account(connector_id: str, user_id: str) -> None:
    """Remove the connector_accounts row for (user_id, connector_id)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM connector_accounts WHERE user_id = %s AND connector_id = %s",
            (user_id, connector_id),  # MUST SCOPE BY USER
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Deduplication helpers ──────────────────────────────────────────────────────


def is_item_imported(connector_id: str, external_id: str, user_id: str) -> bool:
    """Return True if this (user, connector, external_id) has already been imported."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT 1 FROM connector_items
               WHERE user_id = %s AND connector_id = %s AND external_id = %s""",
            (user_id, connector_id, external_id),  # MUST SCOPE BY USER
        )
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


def record_item(
    connector_id: str,
    external_id: str,
    memory_id: str,
    user_id: str,
) -> None:
    """Record a successfully imported item (upsert — re-runs are safe)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO connector_items (user_id, connector_id, external_id, memory_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id, connector_id, external_id) DO UPDATE
               SET memory_id = EXCLUDED.memory_id""",
            (user_id, connector_id, external_id, memory_id),  # MUST SCOPE BY USER
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def count_imported_items(connector_id: str, user_id: str) -> int:
    """Return the number of items imported from a connector for a user."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT COUNT(*) FROM connector_items
               WHERE user_id = %s AND connector_id = %s""",
            (user_id, connector_id),  # MUST SCOPE BY USER
        )
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def get_imported_counts(user_id: str) -> dict[str, int]:
    """Return {connector_id: count} for all connectors for the user."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT connector_id, COUNT(*) FROM connector_items
               WHERE user_id = %s GROUP BY connector_id""",
            (user_id,),  # MUST SCOPE BY USER
        )
        return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()
