"""psycopg2 helpers for the STORIES module.

Every query is scoped by user_id.  # MUST SCOPE BY USER

Watch-progress completion rule (pure Python, matches the spec):
    completed = position_seconds >= 0.9 * duration_seconds
"""

import logging
import uuid
from typing import Optional

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect

logger = logging.getLogger(__name__)

# ── Schema bootstrap ─────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS stories_films (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    premise       TEXT,
    category      VARCHAR(64),
    signal_video_id TEXT,
    video_url     TEXT,
    thumbnail_url TEXT,
    poster_url    TEXT,
    duration_seconds FLOAT,
    status        VARCHAR(16) NOT NULL DEFAULT 'generating'
                      CHECK (status IN ('generating', 'ready', 'failed')),
    error_message TEXT,
    generation_progress JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Backfill for installs created before scene-stitching progress tracking.
ALTER TABLE stories_films ADD COLUMN IF NOT EXISTS generation_progress JSONB DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_stories_films_user_id       ON stories_films (user_id);
CREATE INDEX IF NOT EXISTS idx_stories_films_user_category ON stories_films (user_id, category);
CREATE INDEX IF NOT EXISTS idx_stories_films_user_status   ON stories_films (user_id, status);
CREATE INDEX IF NOT EXISTS idx_stories_films_user_created  ON stories_films (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS stories_series (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    premise       TEXT,
    category      VARCHAR(64),
    poster_url    TEXT,
    thumbnail_url TEXT,
    status        VARCHAR(16) NOT NULL DEFAULT 'generating'
                      CHECK (status IN ('generating', 'ready', 'failed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stories_series_user_id       ON stories_series (user_id);
CREATE INDEX IF NOT EXISTS idx_stories_series_user_category ON stories_series (user_id, category);

CREATE TABLE IF NOT EXISTS stories_episodes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    series_id        UUID NOT NULL REFERENCES stories_series(id) ON DELETE CASCADE,
    season_number    INT NOT NULL DEFAULT 1,
    episode_number   INT NOT NULL,
    title            TEXT NOT NULL,
    premise          TEXT,
    signal_video_id  TEXT,
    video_url        TEXT,
    thumbnail_url    TEXT,
    duration_seconds FLOAT,
    status           VARCHAR(16) NOT NULL DEFAULT 'generating'
                         CHECK (status IN ('generating', 'ready', 'failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_id, season_number, episode_number)
);
CREATE INDEX IF NOT EXISTS idx_stories_episodes_series  ON stories_episodes (series_id, season_number, episode_number);
CREATE INDEX IF NOT EXISTS idx_stories_episodes_user_id ON stories_episodes (user_id);

CREATE TABLE IF NOT EXISTS stories_watch_progress (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_type     VARCHAR(16) NOT NULL CHECK (content_type IN ('film', 'episode')),
    content_id       UUID NOT NULL,
    position_seconds FLOAT NOT NULL DEFAULT 0,
    duration_seconds FLOAT,
    completed        BOOLEAN NOT NULL DEFAULT FALSE,
    last_watched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, content_type, content_id)
);
CREATE INDEX IF NOT EXISTS idx_stories_wp_user_type ON stories_watch_progress (user_id, content_type);
CREATE INDEX IF NOT EXISTS idx_stories_wp_continue  ON stories_watch_progress (user_id, completed, last_watched_at DESC) WHERE completed = FALSE;

CREATE TABLE IF NOT EXISTS stories_liked (
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_type VARCHAR(16) NOT NULL CHECK (content_type IN ('film', 'series', 'episode')),
    content_id   UUID NOT NULL,
    liked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, content_type, content_id)
);
CREATE INDEX IF NOT EXISTS idx_stories_liked_user ON stories_liked (user_id, content_type);
"""


def init_stories_db(conn=None) -> None:
    """Idempotent schema bootstrap — called from the API lifespan (no-arg) or
    with an existing connection."""
    own = conn is None
    if own:
        conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(_DDL)
        conn.commit()
    finally:
        cur.close()
        if own:
            conn.close()


# ── Completion helper (pure Python — no DB) ──────────────────────────────────

def _is_completed(position_seconds: float, duration_seconds: Optional[float]) -> bool:
    """True when position_seconds >= 90 % of duration_seconds.

    Returns False if duration is unknown (None or zero) so incomplete videos
    are never spuriously marked done.
    """
    if not duration_seconds:
        return False
    return position_seconds >= 0.9 * duration_seconds


# ── Films ────────────────────────────────────────────────────────────────────

def insert_film(
    conn,
    *,
    user_id: str,
    title: str,
    premise: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Insert a new film row in 'generating' status. Returns the film id (UUID str).
    # MUST SCOPE BY USER"""
    film_id = str(uuid.uuid4())
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO stories_films (id, user_id, title, premise, category)
               VALUES (%s, %s, %s, %s, %s)""",
            (film_id, user_id, title, premise, category),
        )
        conn.commit()
    finally:
        cur.close()
    return film_id


def update_film_status(
    conn,
    film_id: str,
    status: str,
    *,
    user_id: str,
    signal_video_id: Optional[str] = None,
    video_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    poster_url: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update a film's status and optional media fields. # MUST SCOPE BY USER"""
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE stories_films
               SET status = %s,
                   signal_video_id  = COALESCE(%s, signal_video_id),
                   video_url        = COALESCE(%s, video_url),
                   thumbnail_url    = COALESCE(%s, thumbnail_url),
                   poster_url       = COALESCE(%s, poster_url),
                   duration_seconds = COALESCE(%s, duration_seconds),
                   error_message    = %s,
                   updated_at       = now()
               WHERE id = %s AND user_id = %s""",
            (
                status,
                signal_video_id,
                video_url,
                thumbnail_url,
                poster_url,
                duration_seconds,
                error_message,
                film_id,
                user_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()


def update_film_progress(conn, film_id: str, patch: dict, *, user_id: str) -> None:
    """Merge `patch` into a film's generation_progress JSONB. Called after every
    clip (not batched) by the scene-stitching pipeline. # MUST SCOPE BY USER"""
    import json
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE stories_films
               SET generation_progress = COALESCE(generation_progress, '{}'::jsonb) || %s::jsonb,
                   updated_at = now()
               WHERE id = %s AND user_id = %s""",
            (json.dumps(patch), film_id, user_id),
        )
        conn.commit()
    finally:
        cur.close()


def get_film_progress(conn, film_id: str, *, user_id: str) -> Optional[dict]:
    """Return a film's generation progress with a derived percentage, or None if
    the film does not exist. # MUST SCOPE BY USER

    percent = clips_generated / total_scenes * 100  (0 when total unknown).
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT status, generation_progress FROM stories_films WHERE id = %s AND user_id = %s",
            (film_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        progress = row["generation_progress"] or {}
        total = progress.get("total_scenes") or 0
        done = progress.get("clips_generated") or 0
        percent = round(done / total * 100) if total else (100 if row["status"] == "ready" else 0)
        return {
            "status": row["status"],
            "percent": percent,
            **progress,
        }
    finally:
        cur.close()


def get_film(conn, film_id: str, *, user_id: str) -> Optional[dict]:
    """Fetch a single film row scoped to user_id. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM stories_films WHERE id = %s AND user_id = %s",
            (film_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()


def list_films(
    conn,
    *,
    user_id: str,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """List films for a user, optionally filtered by category. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if category:
            cur.execute(
                """SELECT * FROM stories_films
                   WHERE user_id = %s AND category = %s
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (user_id, category, limit, offset),
            )
        else:
            cur.execute(
                """SELECT * FROM stories_films
                   WHERE user_id = %s
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (user_id, limit, offset),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def get_related_films(conn, film_id: str, category: Optional[str], *, user_id: str, limit: int = 6) -> list[dict]:
    """Return up to `limit` ready films in the same category, excluding the given film.
    Falls back to recent films of any category if category is None.  # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if category:
            cur.execute(
                """SELECT * FROM stories_films
                   WHERE user_id = %s AND category = %s AND id != %s AND status = 'ready'
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, category, film_id, limit),
            )
        else:
            cur.execute(
                """SELECT * FROM stories_films
                   WHERE user_id = %s AND id != %s AND status = 'ready'
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, film_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


# ── Series ───────────────────────────────────────────────────────────────────

def insert_series(
    conn,
    *,
    user_id: str,
    title: str,
    premise: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Insert a new series row. Returns the series id. # MUST SCOPE BY USER"""
    series_id = str(uuid.uuid4())
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO stories_series (id, user_id, title, premise, category)
               VALUES (%s, %s, %s, %s, %s)""",
            (series_id, user_id, title, premise, category),
        )
        conn.commit()
    finally:
        cur.close()
    return series_id


def get_series(conn, series_id: str, *, user_id: str) -> Optional[dict]:
    """Fetch a single series row. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM stories_series WHERE id = %s AND user_id = %s",
            (series_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()


def list_series(conn, *, user_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """List all series for a user. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT * FROM stories_series WHERE user_id = %s
               ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def list_episodes(conn, series_id: str, *, user_id: str) -> list[dict]:
    """List episodes for a series, ordered by season + episode number.
    Verifies the series belongs to user_id.  # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT e.* FROM stories_episodes e
               JOIN stories_series s ON s.id = e.series_id
               WHERE e.series_id = %s AND s.user_id = %s
               ORDER BY e.season_number, e.episode_number""",
            (series_id, user_id),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def insert_episode(
    conn,
    *,
    user_id: str,
    series_id: str,
    season_number: int,
    episode_number: int,
    title: str,
    premise: Optional[str] = None,
) -> str:
    """Insert a new episode. Returns episode id. # MUST SCOPE BY USER"""
    episode_id = str(uuid.uuid4())
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO stories_episodes
               (id, user_id, series_id, season_number, episode_number, title, premise)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (episode_id, user_id, series_id, season_number, episode_number, title, premise),
        )
        conn.commit()
    finally:
        cur.close()
    return episode_id


# ── Watch progress ───────────────────────────────────────────────────────────

def upsert_watch_progress(
    conn,
    *,
    user_id: str,
    content_type: str,
    content_id: str,
    position_seconds: float,
    duration_seconds: Optional[float],
) -> dict:
    """UPSERT watch progress. Completion determined PURELY IN PYTHON (90% rule).
    Returns the resulting row as a dict.  # MUST SCOPE BY USER"""
    completed = _is_completed(position_seconds, duration_seconds)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """INSERT INTO stories_watch_progress
               (user_id, content_type, content_id, position_seconds, duration_seconds,
                completed, last_watched_at)
               VALUES (%s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (user_id, content_type, content_id)
               DO UPDATE SET
                   position_seconds = EXCLUDED.position_seconds,
                   duration_seconds = COALESCE(EXCLUDED.duration_seconds, stories_watch_progress.duration_seconds),
                   completed        = EXCLUDED.completed,
                   last_watched_at  = now()
               RETURNING *""",
            (user_id, content_type, content_id, position_seconds, duration_seconds, completed),
        )
        conn.commit()
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        cur.close()


def get_watch_progress(
    conn,
    *,
    user_id: str,
    content_type: str,
    content_id: str,
) -> Optional[dict]:
    """Fetch watch progress for one item. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT * FROM stories_watch_progress
               WHERE user_id = %s AND content_type = %s AND content_id = %s""",
            (user_id, content_type, content_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()


def continue_watching(conn, *, user_id: str, limit: int = 10) -> list[dict]:
    """In-progress items: completed=false AND position_seconds > 30,
    ordered by last_watched_at DESC.  # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT * FROM stories_watch_progress
               WHERE user_id = %s
                 AND completed = FALSE
                 AND position_seconds > 30
               ORDER BY last_watched_at DESC
               LIMIT %s""",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


# ── Likes ────────────────────────────────────────────────────────────────────

def like_content(conn, *, user_id: str, content_type: str, content_id: str) -> None:
    """Insert a like (idempotent — ON CONFLICT DO NOTHING). # MUST SCOPE BY USER"""
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO stories_liked (user_id, content_type, content_id)
               VALUES (%s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (user_id, content_type, content_id),
        )
        conn.commit()
    finally:
        cur.close()


def unlike_content(conn, *, user_id: str, content_type: str, content_id: str) -> None:
    """Remove a like. # MUST SCOPE BY USER"""
    cur = conn.cursor()
    try:
        cur.execute(
            """DELETE FROM stories_liked
               WHERE user_id = %s AND content_type = %s AND content_id = %s""",
            (user_id, content_type, content_id),
        )
        conn.commit()
    finally:
        cur.close()


def is_liked(conn, *, user_id: str, content_type: str, content_id: str) -> bool:
    """True if the user has liked this item. # MUST SCOPE BY USER"""
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT 1 FROM stories_liked
               WHERE user_id = %s AND content_type = %s AND content_id = %s""",
            (user_id, content_type, content_id),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()


# ── Categories ───────────────────────────────────────────────────────────────

def list_categories(conn, *, user_id: str) -> list[dict]:
    """Return [{"category": str, "film_count": int, "series_count": int}] for the user.

    Counts are computed in pure SQL and merged in Python so a single query per
    table is sufficient.  # MUST SCOPE BY USER
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT category, COUNT(*) AS film_count
               FROM stories_films
               WHERE user_id = %s AND category IS NOT NULL
               GROUP BY category""",
            (user_id,),
        )
        film_rows = {r["category"]: r["film_count"] for r in cur.fetchall()}

        cur.execute(
            """SELECT category, COUNT(*) AS series_count
               FROM stories_series
               WHERE user_id = %s AND category IS NOT NULL
               GROUP BY category""",
            (user_id,),
        )
        series_rows = {r["category"]: r["series_count"] for r in cur.fetchall()}

        all_cats = sorted(set(film_rows) | set(series_rows))
        return [
            {
                "category": cat,
                "film_count": film_rows.get(cat, 0),
                "series_count": series_rows.get(cat, 0),
            }
            for cat in all_cats
        ]
    finally:
        cur.close()


# ── Search ───────────────────────────────────────────────────────────────────

def search_films(conn, query: str, *, user_id: str, limit: int = 20) -> list[dict]:
    """Full-text ILIKE search on films title + premise. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        pattern = f"%{query}%"
        cur.execute(
            """SELECT * FROM stories_films
               WHERE user_id = %s AND (title ILIKE %s OR premise ILIKE %s)
               ORDER BY created_at DESC
               LIMIT %s""",
            (user_id, pattern, pattern, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


def search_series(conn, query: str, *, user_id: str, limit: int = 20) -> list[dict]:
    """Full-text ILIKE search on series title + premise. # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        pattern = f"%{query}%"
        cur.execute(
            """SELECT * FROM stories_series
               WHERE user_id = %s AND (title ILIKE %s OR premise ILIKE %s)
               ORDER BY created_at DESC
               LIMIT %s""",
            (user_id, pattern, pattern, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


# ── Status counts ─────────────────────────────────────────────────────────────

def get_status_counts(conn, *, user_id: str) -> dict:
    """Return counts of generating/ready/failed for films and series.
    # MUST SCOPE BY USER"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT status, COUNT(*) AS cnt FROM stories_films
               WHERE user_id = %s GROUP BY status""",
            (user_id,),
        )
        film_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            """SELECT status, COUNT(*) AS cnt FROM stories_series
               WHERE user_id = %s GROUP BY status""",
            (user_id,),
        )
        series_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

        return {
            "films": {
                "generating": film_counts.get("generating", 0),
                "ready": film_counts.get("ready", 0),
                "failed": film_counts.get("failed", 0),
            },
            "series": {
                "generating": series_counts.get("generating", 0),
                "ready": series_counts.get("ready", 0),
                "failed": series_counts.get("failed", 0),
            },
        }
    finally:
        cur.close()
