"""ARIA database helpers — psycopg2, every query scoped by user_id.
# MUST SCOPE BY USER
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect

logger = logging.getLogger(__name__)

# ── Bootstrap ─────────────────────────────────────────────────────────────────

def init_aria_db() -> None:
    """Apply 0010_aria.sql idempotently at startup."""
    import os
    sql_path = os.path.join(
        os.path.dirname(__file__),
        "../../../..",
        "migrations",
        "0010_aria.sql",
    )
    sql_path = os.path.normpath(sql_path)
    conn = _connect()
    cur = conn.cursor()
    try:
        if os.path.exists(sql_path):
            with open(sql_path) as f:
                cur.execute(f.read())
        else:
            # Inline fallback (migration file missing — e.g. tests)
            _apply_inline_ddl(cur)
        # Suno provenance columns (mirrors migration 0014_aria_suno.sql).
        # Idempotent so startup is safe whether or not 0014 ran separately.
        cur.execute(
            "ALTER TABLE aria_tracks "
            "ADD COLUMN IF NOT EXISTS suno_job_id VARCHAR(255), "
            "ADD COLUMN IF NOT EXISTS generation_provider VARCHAR(50) DEFAULT 'suno'"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("init_aria_db failed")
    finally:
        cur.close()
        conn.close()
    # Self-heal duplicate auto-generated playlists + install the guard index
    # (mirrors migrations/0019_aria_playlist_dedupe.sql). Own transaction so a
    # failure here cannot roll back the DDL above.
    dedupe_auto_playlists()


def dedupe_auto_playlists() -> None:
    """Merge duplicate auto-generated playlists per (user_id, dominant_mood) and
    install a NULLS-NOT-DISTINCT partial unique index to prevent recurrence.

    Duplicates arose because auto-playlist ids were derived from the resolved
    user_id (uuid5), which changed across runs when MCP/cron generation rebound
    from the seed admin to the real platform user (migration 0016). Idempotent —
    a no-op once the library is clean. # MUST SCOPE BY USER (per-user partitions)
    """
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """CREATE TEMP TABLE _aria_pl_dupes ON COMMIT DROP AS
               SELECT id,
                      FIRST_VALUE(id) OVER (
                          PARTITION BY user_id, COALESCE(dominant_mood::text, '__brain__')
                          ORDER BY created_at, id
                      ) AS keep_id
               FROM aria_playlists
               WHERE is_auto_generated = TRUE"""
        )
        cur.execute(
            """INSERT INTO aria_playlist_tracks (playlist_id, track_id, position)
               SELECT d.keep_id, pt.track_id, pt.position
               FROM aria_playlist_tracks pt
               JOIN _aria_pl_dupes d ON d.id = pt.playlist_id
               WHERE d.id <> d.keep_id
               ON CONFLICT (playlist_id, track_id) DO NOTHING"""
        )
        cur.execute(
            "DELETE FROM aria_playlist_tracks "
            "WHERE playlist_id IN (SELECT id FROM _aria_pl_dupes WHERE id <> keep_id)"
        )
        cur.execute(
            "DELETE FROM aria_playlists "
            "WHERE id IN (SELECT id FROM _aria_pl_dupes WHERE id <> keep_id)"
        )
        cur.execute(
            """UPDATE aria_playlists p
               SET track_count    = COALESCE(sub.cnt, 0),
                   total_duration = COALESCE(sub.dur, 0),
                   updated_at     = now()
               FROM (
                   SELECT pt.playlist_id,
                          COUNT(*)                             AS cnt,
                          COALESCE(SUM(t.duration_seconds), 0) AS dur
                   FROM aria_playlist_tracks pt
                   JOIN aria_tracks t ON t.id = pt.track_id
                   GROUP BY pt.playlist_id
               ) sub
               WHERE p.id = sub.playlist_id AND p.is_auto_generated = TRUE"""
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("dedupe_auto_playlists: merge step failed")
    finally:
        cur.close()
        conn.close()
    # The guard index in a separate transaction: NULLS NOT DISTINCT requires
    # PostgreSQL 15+, so isolate it — on an older engine the merge above still
    # persists and we just skip the index.
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_aria_playlists_auto_natural
               ON aria_playlists (user_id, dominant_mood) NULLS NOT DISTINCT
               WHERE is_auto_generated"""
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.warning(
            "dedupe_auto_playlists: could not create guard index "
            "(needs PostgreSQL 15+); duplicates were still merged"
        )
    finally:
        cur.close()
        conn.close()


def _apply_inline_ddl(cur) -> None:
    """Minimal inline DDL (used when migration file is absent — e.g. CI)."""
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'aria_mood') THEN
                CREATE TYPE aria_mood AS ENUM (
                    'calm','focus','energetic','melancholic','uplifting','tense'
                );
            END IF;
        END $$;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aria_tracks (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL,
            title            TEXT NOT NULL,
            mood             aria_mood NOT NULL,
            genre            TEXT NOT NULL DEFAULT '',
            topic_category   TEXT NOT NULL DEFAULT '',
            duration_seconds INT,
            status           VARCHAR(16) NOT NULL DEFAULT 'generating',
            audio_s3_key     TEXT,
            waveform_s3_key  TEXT,
            art_s3_key       TEXT,
            lyrics           TEXT,
            bpm              INT,
            musical_key      TEXT,
            instruments      TEXT[],
            brain_topic_ids  UUID[],
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aria_playlists (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL,
            title             TEXT NOT NULL,
            dominant_mood     aria_mood,
            art_s3_key        TEXT,
            track_count       INT NOT NULL DEFAULT 0,
            total_duration    INT NOT NULL DEFAULT 0,
            is_auto_generated BOOLEAN NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aria_playlist_tracks (
            playlist_id  UUID NOT NULL,
            track_id     UUID NOT NULL,
            position     INT NOT NULL DEFAULT 0,
            PRIMARY KEY (playlist_id, track_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aria_liked_tracks (
            user_id   UUID NOT NULL,
            track_id  UUID NOT NULL,
            liked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, track_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aria_play_history (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id               UUID NOT NULL,
            track_id              UUID NOT NULL,
            started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at              TIMESTAMPTZ,
            play_duration_seconds INT
        )
    """)


# ── Tracks ─────────────────────────────────────────────────────────────────────

def insert_track(
    *,
    user_id: str,
    track_id: str,
    title: str,
    mood: str,
    genre: str = "",
    topic_category: str = "",
    lyrics: str = "",
    bpm: Optional[int] = None,
    musical_key: str = "",
    instruments: Optional[list[str]] = None,
    brain_topic_ids: Optional[list[str]] = None,
) -> None:
    """Insert a track row with status='generating'. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO aria_tracks
               (id, user_id, title, mood, genre, topic_category, lyrics, bpm,
                musical_key, instruments, brain_topic_ids, status)
               VALUES (%s, %s, %s, %s::aria_mood, %s, %s, %s, %s, %s, %s, %s, 'generating')""",
            (
                track_id, user_id, title, mood, genre, topic_category, lyrics,
                bpm, musical_key,
                instruments or [],
                brain_topic_ids or [],
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def update_track_status(
    track_id: str,
    status: str,
    *,
    user_id: str,
    audio_s3_key: Optional[str] = None,
    waveform_s3_key: Optional[str] = None,
    art_s3_key: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    suno_job_id: Optional[str] = None,
) -> None:
    """Update a track's status and optional S3 keys. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE aria_tracks
               SET status = %s,
                   audio_s3_key    = COALESCE(%s, audio_s3_key),
                   waveform_s3_key = COALESCE(%s, waveform_s3_key),
                   art_s3_key      = COALESCE(%s, art_s3_key),
                   duration_seconds = COALESCE(%s, duration_seconds),
                   suno_job_id     = COALESCE(%s, suno_job_id),
                   updated_at      = now()
               WHERE id = %s AND user_id = %s""",
            (
                status, audio_s3_key, waveform_s3_key, art_s3_key,
                duration_seconds, suno_job_id, track_id, user_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_track(track_id: str, *, user_id: str) -> Optional[dict]:
    """Fetch a single track by id, scoped to user. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM aria_tracks WHERE id = %s AND user_id = %s",
            (track_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()


def list_tracks(
    *,
    user_id: str,
    mood: Optional[str] = None,
    topic_category: Optional[str] = None,
    status: Optional[str] = "ready",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List tracks for the user, optionally filtered. # MUST SCOPE BY USER"""
    assert user_id is not None
    parts = ["WHERE t.user_id = %s"]
    params: list = [user_id]
    if mood:
        parts.append("AND t.mood = %s::aria_mood")
        params.append(mood)
    if topic_category:
        parts.append("AND t.topic_category = %s")
        params.append(topic_category)
    if status:
        parts.append("AND t.status = %s")
        params.append(status)
    params.extend([limit, offset])

    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            f"""SELECT t.*,
                       (SELECT liked_at FROM aria_liked_tracks
                        WHERE user_id = t.user_id AND track_id = t.id) IS NOT NULL AS is_liked
                FROM aria_tracks t
                {" ".join(parts)}
                ORDER BY t.created_at DESC
                LIMIT %s OFFSET %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def search_tracks(query: str, *, user_id: str, limit: int = 20) -> list[dict]:
    """Full-text substring search on title/genre/topic_category. # MUST SCOPE BY USER"""
    assert user_id is not None
    q = f"%{query.lower()}%"
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT * FROM aria_tracks
               WHERE user_id = %s AND status = 'ready'
                 AND (lower(title) LIKE %s
                   OR lower(genre) LIKE %s
                   OR lower(topic_category) LIKE %s)
               ORDER BY created_at DESC
               LIMIT %s""",
            (user_id, q, q, q, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def count_tracks(*, user_id: str) -> dict:
    """Return track counts by status for the user. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT status, COUNT(*) as count FROM aria_tracks
               WHERE user_id = %s GROUP BY status""",
            (user_id,),
        )
        return {row["status"]: row["count"] for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


# ── Likes ──────────────────────────────────────────────────────────────────────

def like_track(track_id: str, *, user_id: str) -> None:
    """Like a track (idempotent). # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO aria_liked_tracks (user_id, track_id)
               VALUES (%s, %s) ON CONFLICT DO NOTHING""",
            (user_id, track_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def unlike_track(track_id: str, *, user_id: str) -> None:
    """Remove a like (idempotent). # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM aria_liked_tracks WHERE user_id = %s AND track_id = %s",
            (user_id, track_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Play history ───────────────────────────────────────────────────────────────

def record_play_start(play_id: str, track_id: str, *, user_id: str) -> None:
    """Insert a play row at start time. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO aria_play_history (id, user_id, track_id)
               VALUES (%s, %s, %s)""",
            (play_id, user_id, track_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def record_play_end(
    play_id: str,
    play_duration_seconds: int,
    *,
    user_id: str,
) -> None:
    """Complete a play record with duration. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE aria_play_history
               SET ended_at = now(), play_duration_seconds = %s
               WHERE id = %s AND user_id = %s""",
            (play_duration_seconds, play_id, user_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def recently_played(*, user_id: str, limit: int = 20) -> list[dict]:
    """Most recently started plays (distinct tracks) for a user. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT DISTINCT ON (h.track_id)
                      h.track_id, h.started_at, h.play_duration_seconds,
                      t.title, t.mood, t.duration_seconds, t.audio_s3_key,
                      t.waveform_s3_key, t.art_s3_key
               FROM aria_play_history h
               JOIN aria_tracks t ON t.id = h.track_id
               WHERE h.user_id = %s AND t.status = 'ready'
               ORDER BY h.track_id, h.started_at DESC
               LIMIT %s""",
            (user_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def recently_played_track_ids(
    *,
    user_id: str,
    since_days: int = 7,
) -> set[str]:
    """Track IDs played by this user in the last `since_days` days.
    Used by queue_next to avoid re-playing recent tracks. # MUST SCOPE BY USER"""
    assert user_id is not None
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT DISTINCT track_id FROM aria_play_history
               WHERE user_id = %s AND started_at >= %s""",
            (user_id, cutoff),
        )
        return {str(row[0]) for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


# ── Playlists ──────────────────────────────────────────────────────────────────

def create_playlist(
    *,
    playlist_id: str,
    user_id: str,
    title: str,
    dominant_mood: Optional[str] = None,
    art_s3_key: Optional[str] = None,
    is_auto_generated: bool = False,
) -> None:
    """Create a playlist row. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO aria_playlists
               (id, user_id, title, dominant_mood, art_s3_key, is_auto_generated)
               VALUES (%s, %s, %s, %s::aria_mood, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (playlist_id, user_id, title, dominant_mood, art_s3_key, is_auto_generated),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def upsert_playlist(
    *,
    playlist_id: str,
    user_id: str,
    title: str,
    dominant_mood: Optional[str] = None,
    art_s3_key: Optional[str] = None,
    is_auto_generated: bool = False,
) -> str:
    """Insert or update a playlist row (used by auto-grouping); returns the
    canonical playlist id actually written.

    For auto-generated playlists, identity is the natural key
    (user_id, dominant_mood) — NULL mood is the single "From Your Brain"
    catch-all — NOT the supplied `playlist_id`. The supplied id is derived from
    the resolved user_id, which can change across runs (seed-admin vs platform
    user, migration 0016); keying on it produced duplicate rows. We reuse any
    existing per-mood playlist's id so callers append to the right row.
    # MUST SCOPE BY USER
    """
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        existing_id = None
        if is_auto_generated:
            cur.execute(
                """SELECT id FROM aria_playlists
                   WHERE user_id = %s AND is_auto_generated = TRUE
                     AND dominant_mood IS NOT DISTINCT FROM %s::aria_mood
                   ORDER BY created_at, id
                   LIMIT 1""",
                (user_id, dominant_mood),
            )
            row = cur.fetchone()
            if row:
                existing_id = row[0]

        if existing_id is not None:
            cur.execute(
                """UPDATE aria_playlists
                   SET title = %s,
                       dominant_mood = %s::aria_mood,
                       art_s3_key = COALESCE(%s, art_s3_key),
                       is_auto_generated = %s,
                       updated_at = now()
                   WHERE id = %s AND user_id = %s""",
                (title, dominant_mood, art_s3_key, is_auto_generated, existing_id, user_id),
            )
            conn.commit()
            return str(existing_id)

        cur.execute(
            """INSERT INTO aria_playlists
               (id, user_id, title, dominant_mood, art_s3_key, is_auto_generated)
               VALUES (%s, %s, %s, %s::aria_mood, %s, %s)
               ON CONFLICT (id) DO UPDATE
               SET title = EXCLUDED.title,
                   dominant_mood = EXCLUDED.dominant_mood,
                   art_s3_key = COALESCE(EXCLUDED.art_s3_key, aria_playlists.art_s3_key),
                   is_auto_generated = EXCLUDED.is_auto_generated,
                   updated_at = now()
               RETURNING id""",
            (playlist_id, user_id, title, dominant_mood, art_s3_key, is_auto_generated),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        return str(new_id)
    finally:
        cur.close()
        conn.close()


def get_playlist(playlist_id: str, *, user_id: str) -> Optional[dict]:
    """Fetch playlist + tracks. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM aria_playlists WHERE id = %s AND user_id = %s",
            (playlist_id, user_id),
        )
        pl = cur.fetchone()
        if pl is None:
            return None
        pl = dict(pl)
        cur.execute(
            """SELECT t.* FROM aria_tracks t
               JOIN aria_playlist_tracks pt ON pt.track_id = t.id
               WHERE pt.playlist_id = %s AND t.status = 'ready'
               ORDER BY pt.position""",
            (playlist_id,),
        )
        pl["tracks"] = [dict(r) for r in cur.fetchall()]
        return pl
    finally:
        cur.close()
        conn.close()


def list_playlists(*, user_id: str) -> list[dict]:
    """List all playlists for a user (without track details). # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM aria_playlists WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def add_tracks_to_playlist(
    playlist_id: str,
    track_ids: list[str],
    *,
    user_id: str,
) -> None:
    """Append tracks to a playlist, recomputing counts. # MUST SCOPE BY USER"""
    assert user_id is not None
    conn = _connect()
    cur = conn.cursor()
    try:
        # get current max position
        cur.execute(
            "SELECT COALESCE(MAX(position), -1) FROM aria_playlist_tracks WHERE playlist_id = %s",
            (playlist_id,),
        )
        pos = cur.fetchone()[0] + 1
        for tid in track_ids:
            cur.execute(
                """INSERT INTO aria_playlist_tracks (playlist_id, track_id, position)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (playlist_id, tid, pos),
            )
            pos += 1
        # recompute counts
        cur.execute(
            """UPDATE aria_playlists
               SET track_count = (
                       SELECT COUNT(*) FROM aria_playlist_tracks
                       WHERE playlist_id = %s
                   ),
                   total_duration = (
                       SELECT COALESCE(SUM(t.duration_seconds), 0)
                       FROM aria_playlist_tracks pt
                       JOIN aria_tracks t ON t.id = pt.track_id
                       WHERE pt.playlist_id = %s
                   ),
                   updated_at = now()
               WHERE id = %s AND user_id = %s""",
            (playlist_id, playlist_id, playlist_id, user_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Queue logic (pure Python) ──────────────────────────────────────────────────

def queue_next(
    *,
    user_id: str,
    current_track_id: Optional[str] = None,
    explicit_queue: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    Four-tier queue selection (pure Python, no LLM):
      1. explicit_queue (caller-provided ordered list) — first entry not yet played.
      2. Same mood as current_track, not played in the last 7 days.
      3. Any ready track not yet played by this user (unplayed).
      4. Least-recently-played ready track.

    Returns the full track dict or None if the user has no ready tracks.
    # MUST SCOPE BY USER
    """
    assert user_id is not None

    # Tier 1 — explicit queue
    if explicit_queue:
        played_ids = recently_played_track_ids(user_id=user_id, since_days=7)
        for tid in explicit_queue:
            if tid not in played_ids:
                t = get_track(tid, user_id=user_id)
                if t and t["status"] == "ready":
                    return t
        # all explicit entries played recently — fall through

    recent_ids = recently_played_track_ids(user_id=user_id, since_days=7)

    # Tier 2 — same mood as current, not recently played
    if current_track_id:
        current = get_track(current_track_id, user_id=user_id)
        if current:
            same_mood = list_tracks(
                user_id=user_id,
                mood=str(current["mood"]),
                status="ready",
                limit=100,
            )
            for t in same_mood:
                if str(t["id"]) != current_track_id and str(t["id"]) not in recent_ids:
                    return t

    # Tier 3 — any unplayed track
    all_tracks = list_tracks(user_id=user_id, status="ready", limit=200)
    played_ever = _all_played_track_ids(user_id=user_id)
    for t in all_tracks:
        if str(t["id"]) not in played_ever:
            return t

    # Tier 4 — least-recently-played
    return _least_recently_played(user_id=user_id)


def _all_played_track_ids(*, user_id: str) -> set[str]:
    """All track IDs ever played by this user. # MUST SCOPE BY USER"""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT track_id FROM aria_play_history WHERE user_id = %s",
            (user_id,),
        )
        return {str(row[0]) for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def _least_recently_played(*, user_id: str) -> Optional[dict]:
    """Track played longest ago (or never), scoped to user. # MUST SCOPE BY USER"""
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT t.* FROM aria_tracks t
               LEFT JOIN (
                   SELECT track_id, MAX(started_at) AS last_played
                   FROM aria_play_history
                   WHERE user_id = %s
                   GROUP BY track_id
               ) ph ON ph.track_id = t.id
               WHERE t.user_id = %s AND t.status = 'ready'
               ORDER BY ph.last_played ASC NULLS FIRST
               LIMIT 1""",
            (user_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        cur.close()
        conn.close()
