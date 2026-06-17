"""Shared global creator personas for the PULSE pipeline.

`content_creators` has an optional `user_id` column added by migration 0015:
  - NULL  = global basic persona, visible to ALL users as a universal fallback.
  - non-NULL = persona generated specifically for that user's brain.

`seed_default_creators()` inserts/updates the GLOBAL basics (user_id = NULL).
These are intentionally language-neutral and topic-neutral — no EU/Swiss bias.
"""

import uuid
from datetime import datetime
from typing import Optional

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect

# Global basics — neutral, universal topics.  No country/region affinities.
# Each is kept deliberately broad so any user's feed gets reasonable content
# even before per-user personas are generated.
_DEFAULT_CREATORS = [
    {
        "slug": "global-science-desk",
        "name": "Global Science Desk",
        "bio": "Science communicator. Turns complex research into clear, honest prose.",
        "style_prompt": (
            "Write like a seasoned science journalist: precise, curious, "
            "jargon-free. Lead with the finding, not the methodology. "
            "One concrete analogy per post. Never sensationalise."
        ),
        "polly_voice_id": "Arthur",
        "polly_language_code": "en-GB",
        "topic_affinities": ["science", "research", "technology", "health", "space", "biology"],
    },
    {
        "slug": "world-sport-desk",
        "name": "World Sport Desk",
        "bio": "Sports analyst covering the human side of athletic achievement worldwide.",
        "style_prompt": (
            "Write like a thoughtful sports commentator who cares about the person "
            "behind the result. Short punchy sentences. Stats serve the story, "
            "not the other way around. Avoid clichés like 'gave 110 percent'."
        ),
        "polly_voice_id": "Matthew",
        "polly_language_code": "en-US",
        "topic_affinities": ["sport", "fitness", "athletics", "football", "basketball", "tennis", "olympics"],
    },
    {
        "slug": "curious-mind",
        "name": "Curious Mind",
        "bio": "Generalist thinker. Finds the unexpected angle on everyday phenomena.",
        "style_prompt": (
            "Write like someone who just learned something delightful and cannot "
            "wait to share it. Warm, conversational, precise. Open with the "
            "surprising fact; close with an implication. Never preachy."
        ),
        "polly_voice_id": "Olivia",
        "polly_language_code": "en-AU",
        "topic_affinities": ["culture", "history", "psychology", "economics", "ideas", "trivia", "nature"],
    },
]


def seed_default_creators() -> int:
    """Insert or update the global (user_id=NULL) default creator personas.

    Idempotent: existing slugs are kept and their voice settings are patched
    to match this config (so a redeploy repairs rows seeded with an earlier
    voice set). Returns the count of newly inserted rows.
    """
    conn = _connect()
    cur = conn.cursor()
    inserted = 0
    try:
        for c in _DEFAULT_CREATORS:
            cur.execute("SELECT id FROM content_creators WHERE slug = %s", (c["slug"],))
            if cur.fetchone() is not None:
                # Repair voice settings on re-deploy; do not overwrite user-
                # authored fields like bio or style_prompt so admins can customise.
                cur.execute(
                    "UPDATE content_creators "
                    "SET polly_voice_id = %s, polly_language_code = %s "
                    "WHERE slug = %s",
                    (c["polly_voice_id"], c["polly_language_code"], c["slug"]),
                )
                continue
            cur.execute(
                """INSERT INTO content_creators
                   (id, slug, name, bio, style_prompt,
                    polly_voice_id, polly_language_code, topic_affinities,
                    user_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)""",
                (
                    str(uuid.uuid4()),
                    c["slug"],
                    c["name"],
                    c["bio"],
                    c["style_prompt"],
                    c["polly_voice_id"],
                    c["polly_language_code"],
                    c["topic_affinities"],
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return inserted


def list_creators(active_only: bool = True, user_id: Optional[str] = None) -> list[dict]:
    """List creators visible to one user: the global basics (user_id IS NULL)
    plus that user's own brain-generated personas.

    Scoping by user_id is REQUIRED for any user-facing call — per-user personas
    (migration 0015) are private, so an unscoped list leaks every tenant's
    personas into everyone's "People" sidebar. Passing user_id=None returns the
    full cross-tenant set and must only be used by admin/maintenance code.
    # MUST SCOPE BY USER
    """
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    where = ["is_active = TRUE"] if active_only else []
    params: list = []
    if user_id is not None:
        where.append("(user_id IS NULL OR user_id = %s)")
        params.append(user_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    cur.execute(f"SELECT * FROM content_creators{clause} ORDER BY name", params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        if isinstance(item.get("created_at"), datetime):
            item["created_at"] = item["created_at"].isoformat()
        result.append(item)
    return result
