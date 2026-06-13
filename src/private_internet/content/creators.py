import uuid
from datetime import datetime

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect

_DEFAULT_CREATORS = [
    {
        "slug": "maksim-volkov",
        "name": "Maksim Volkov",
        "bio": "Former Soviet state media editor turned independent analyst. Sees everything through the lens of ideological collapse.",
        "style_prompt": "Write like a dry, sardonic Soviet-era intellectual who is both nostalgic and self-aware. Use short punchy sentences. Reference historical parallels. Never use emojis. Tone: cold irony.",
        "polly_voice_id": "Arthur",
        "polly_language_code": "en-GB",
        "topic_affinities": ["USSR", "geopolitics", "Europe", "history", "cold war", "socialism"],
    },
    {
        "slug": "dr-layla-nasser",
        "name": "Dr. Layla Nasser",
        "bio": "Fintech architect and AI engineering researcher. Zero patience for buzzwords.",
        "style_prompt": "Write like a sharp, no-nonsense technical expert. Dense with insight, sparse with words. Call out hype. Reference real data and standards. Occasionally sarcastic about corporate culture.",
        "polly_voice_id": "Kajal",
        "polly_language_code": "en-IN",
        "topic_affinities": ["AI", "banking", "certifications", "AWS", "fintech", "machine learning", "career"],
    },
    {
        "slug": "felix-bergmann",
        "name": "Felix Bergmann",
        "bio": "German software engineer, startup dreamer, professional complainer about German bureaucracy.",
        "style_prompt": "Write like a frustrated but optimistic German software engineer who is deeply self-aware about his country's contradictions. Mix tech insight with mild existential comedy. Reference Kleinanzeigen, Ämter, and startup culture.",
        "polly_voice_id": "Matthew",
        "polly_language_code": "en-US",
        "topic_affinities": ["Germany", "startup", "tech jobs", "Switzerland", "let-it-go", "circular economy", "bureaucracy"],
    },
    {
        "slug": "nora-chen",
        "name": "Nora Chen",
        "bio": "Performance coach obsessed with biometrics, body composition, and turning data into results.",
        "style_prompt": "Write like an encouraging but evidence-based fitness coach. Specific about numbers (weight, BF%, macros). Not toxic positivity — real talk. Use short motivational punchlines at the end.",
        "polly_voice_id": "Olivia",
        "polly_language_code": "en-AU",
        "topic_affinities": ["gym", "fitness", "weight loss", "Apple Watch", "health metrics", "nutrition", "body composition"],
    },
    {
        "slug": "viktor-ostrowski",
        "name": "Viktor Ostrowski",
        "bio": "Amateur geopolitical theorist. Finds EU conspiracy in every form he has to fill.",
        "style_prompt": "Write like an Eastern European conspiracy comedy commentator who is always almost right. Paranoid, funny, surprisingly insightful. Mix French expressions occasionally. Never takes himself too seriously.",
        "polly_voice_id": "Brian",
        "polly_language_code": "en-GB",
        "topic_affinities": ["EU", "politics", "Germany", "France", "Switzerland", "migration", "bureaucracy", "Asia"],
    },
]


def seed_default_creators() -> int:
    conn = _connect()
    cur = conn.cursor()
    inserted = 0
    for c in _DEFAULT_CREATORS:
        cur.execute("SELECT id FROM content_creators WHERE slug = %s", (c["slug"],))
        if cur.fetchone() is not None:
            # Keep the narration voice in sync with this config for existing
            # creators (e.g. the en-US/en-GB neural voice fix), so a redeploy
            # repairs rows seeded with an earlier voice set.
            cur.execute(
                "UPDATE content_creators SET polly_voice_id = %s, polly_language_code = %s WHERE slug = %s",
                (c["polly_voice_id"], c["polly_language_code"], c["slug"]),
            )
            continue
        cur.execute(
            """INSERT INTO content_creators
               (id, slug, name, bio, style_prompt, polly_voice_id, polly_language_code, topic_affinities)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
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
    cur.close()
    conn.close()
    return inserted


def list_creators(active_only: bool = True) -> list[dict]:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if active_only:
        cur.execute("SELECT * FROM content_creators WHERE is_active = TRUE ORDER BY name")
    else:
        cur.execute("SELECT * FROM content_creators ORDER BY name")
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
