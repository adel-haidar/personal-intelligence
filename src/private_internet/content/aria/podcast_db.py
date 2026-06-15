"""ARIA podcast database helpers — psycopg2, every query scoped by user_id.

Two-host AI podcasts generated from brain memory clusters. Mirrors the shape of
aria/db.py (tracks) but for the aria_podcasts table.
# MUST SCOPE BY USER
"""

import json
import logging
import os
from typing import Optional

from psycopg2.extras import Json, RealDictCursor

from private_internet.database import _connect

logger = logging.getLogger(__name__)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def init_aria_podcast_db() -> None:
    """Apply 0013_aria_podcasts.sql idempotently at startup."""
    sql_path = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), "../../../..", "migrations", "0013_aria_podcasts.sql"
        )
    )
    conn = _connect()
    cur = conn.cursor()
    try:
        if os.path.exists(sql_path):
            with open(sql_path) as f:
                cur.execute(f.read())
        else:
            _apply_inline_ddl(cur)
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("init_aria_podcast_db failed")
    finally:
        cur.close()
        conn.close()


def _apply_inline_ddl(cur) -> None:
    """Minimal inline DDL (used when migration file is absent — e.g. CI)."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aria_podcasts (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL,
            title            VARCHAR(255) NOT NULL,
            description      TEXT,
            topic_category   VARCHAR(100),
            duration_seconds INTEGER,
            status           VARCHAR(20) NOT NULL DEFAULT 'generating',
            audio_s3_key     VARCHAR(500),
            waveform_s3_key  VARCHAR(500),
            art_s3_key       VARCHAR(500),
            transcript       JSONB,
            brain_topic_ids  UUID[],
            host_a_name      VARCHAR(100) NOT NULL DEFAULT 'Alex',
            host_b_name      VARCHAR(100) NOT NULL DEFAULT 'Jordan',
            language_code    VARCHAR(10) NOT NULL DEFAULT 'en',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS aria_liked_podcasts (
            user_id    UUID NOT NULL,
            podcast_id UUID NOT NULL,
            liked_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, podcast_id)
        )
        """
    )


# ── Inserts / updates ───────────────────────────────────────────────────────────

def insert_podcast(
    *,
    user_id: str,
    podcast_id: str,
    title: str,
    description: str = "",
    topic_category: str = "",
    transcript: Optional[list[dict]] = None,
    brain_topic_ids: Optional[list[str]] = None,
    host_a_name: str = "Alex",
    host_b_name: str = "Jordan",
    language_code: str = "en",
) -> None:
    """Insert a podcast row with status='generating'. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO aria_podcasts
               (id, user_id, title, description, topic_category, transcript,
                brain_topic_ids, host_a_name, host_b_name, language_code, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'generating')""",
            (
                podcast_id, user_id, title, description, topic_category,
                Json(transcript or []),
                brain_topic_ids or [],
                host_a_name, host_b_name, language_code,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def update_podcast_status(
    podcast_id: str,
    status: str,
    *,
    user_id: str,
    audio_s3_key: Optional[str] = None,
    waveform_s3_key: Optional[str] = None,
    art_s3_key: Optional[str] = None,
    duration_seconds: Optional[int] = None,
) -> None:
    """Update a podcast's status and optional S3 keys. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE aria_podcasts
               SET status = %s,
                   audio_s3_key     = COALESCE(%s, audio_s3_key),
                   waveform_s3_key  = COALESCE(%s, waveform_s3_key),
                   art_s3_key       = COALESCE(%s, art_s3_key),
                   duration_seconds = COALESCE(%s, duration_seconds)
               WHERE id = %s AND user_id = %s""",
            (
                status, audio_s3_key, waveform_s3_key, art_s3_key,
                duration_seconds, podcast_id, user_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Reads ───────────────────────────────────────────────────────────────────────

def get_podcast(podcast_id: str, *, user_id: str) -> Optional[dict]:
    """Fetch a single podcast by id, scoped to user, with is_liked. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT p.*,
                      (SELECT liked_at FROM aria_liked_podcasts
                       WHERE user_id = p.user_id AND podcast_id = p.id) IS NOT NULL
                      AS is_liked
               FROM aria_podcasts p
               WHERE p.id = %s AND p.user_id = %s""",
            (podcast_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def list_podcasts(
    *,
    user_id: str,
    status: Optional[str] = "ready",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List podcasts for the user, newest first. # MUST SCOPE BY USER"""
    assert user_id is not None
    parts = ["WHERE p.user_id = %s"]
    params: list = [user_id]
    if status:
        parts.append("AND p.status = %s")
        params.append(status)
    params.extend([limit, offset])
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            f"""SELECT p.*,
                       (SELECT liked_at FROM aria_liked_podcasts
                        WHERE user_id = p.user_id AND podcast_id = p.id) IS NOT NULL
                       AS is_liked
                FROM aria_podcasts p
                {" ".join(parts)}
                ORDER BY p.created_at DESC
                LIMIT %s OFFSET %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def count_podcasts(*, user_id: str) -> dict:
    """Return podcast counts by status for the user. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT status, COUNT(*) AS count FROM aria_podcasts
               WHERE user_id = %s GROUP BY status""",
            (user_id,),
        )
        return {row["status"]: row["count"] for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


# ── Likes ──────────────────────────────────────────────────────────────────────

def like_podcast(podcast_id: str, *, user_id: str) -> None:
    """Like a podcast (idempotent). # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO aria_liked_podcasts (user_id, podcast_id)
               VALUES (%s, %s) ON CONFLICT DO NOTHING""",
            (user_id, podcast_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def unlike_podcast(podcast_id: str, *, user_id: str) -> None:
    """Remove a podcast like (idempotent). # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM aria_liked_podcasts WHERE user_id = %s AND podcast_id = %s",
            (user_id, podcast_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
