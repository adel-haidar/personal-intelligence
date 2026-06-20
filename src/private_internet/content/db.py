from private_internet.database import _connect


def init_content_db() -> None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_creators (
            id TEXT PRIMARY KEY,
            slug VARCHAR(64) UNIQUE NOT NULL,
            name VARCHAR(128) NOT NULL,
            avatar_url TEXT,
            bio TEXT,
            style_prompt TEXT NOT NULL,
            polly_voice_id VARCHAR(64) NOT NULL,
            polly_language_code VARCHAR(16) NOT NULL,
            topic_affinities TEXT[],
            score FLOAT DEFAULT 0.7,
            total_interactions INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_topics (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug VARCHAR(256) UNIQUE NOT NULL,
            source VARCHAR(32) NOT NULL,
            source_ref TEXT,
            keywords TEXT[],
            weight FLOAT DEFAULT 0.5,
            used_count INT DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_research (
            id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL REFERENCES content_topics(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            fetched_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_posts (
            id TEXT PRIMARY KEY,
            creator_id TEXT NOT NULL REFERENCES content_creators(id),
            topic_id TEXT NOT NULL REFERENCES content_topics(id),
            body TEXT NOT NULL,
            image_url TEXT,
            image_prompt TEXT,
            tone VARCHAR(32),
            score FLOAT DEFAULT 0.5,
            total_interactions INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_videos (
            id TEXT PRIMARY KEY,
            creator_id TEXT NOT NULL REFERENCES content_creators(id),
            topic_id TEXT NOT NULL REFERENCES content_topics(id),
            title TEXT NOT NULL,
            description TEXT,
            script TEXT NOT NULL,
            video_url TEXT,
            thumbnail_url TEXT,
            duration_seconds INT,
            status VARCHAR(32) DEFAULT 'pending',
            score FLOAT DEFAULT 0.5,
            total_interactions INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_interactions (
            id TEXT PRIMARY KEY,
            content_id TEXT NOT NULL,
            content_type VARCHAR(16) NOT NULL,
            action VARCHAR(32) NOT NULL,
            watch_pct FLOAT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    # Added after P1: topic keywords feed the P3 creator-affinity matching.
    cur.execute("ALTER TABLE content_topics ADD COLUMN IF NOT EXISTS keywords TEXT[]")

    # PULSE storytelling-format rewrite: record which of the six formats the
    # generator chose, for later per-mood/topic performance analysis.
    cur.execute("ALTER TABLE content_posts ADD COLUMN IF NOT EXISTS post_format VARCHAR(50)")

    # SIGNAL scene-stitching: per-clip generation progress for the long-form
    # video pipeline (total_scenes, clips_generated, current_stage, …).
    cur.execute("ALTER TABLE content_videos ADD COLUMN IF NOT EXISTS generation_progress JSONB DEFAULT '{}'")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_creator ON content_posts(creator_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_topic ON content_posts(topic_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_created ON content_posts(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_status ON content_videos(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_created ON content_videos(created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interactions_content ON content_interactions(content_id, content_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_topics_weight ON content_topics(weight DESC)")

    # Migration 0015: per-user personas — content_creators gains a nullable
    # user_id column so user-specific AI-generated personas can coexist with
    # the global shared basics (user_id = NULL).
    cur.execute(
        "ALTER TABLE content_creators ADD COLUMN IF NOT EXISTS user_id UUID"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_creators_user_id ON content_creators(user_id)"
    )

    # Migration 0022: remove the five owner-flavoured legacy global personas
    # (Felix Bergmann, Dr. Layla Nasser, Maksim Volkov, Nora Chen,
    # Viktor Ostrowski) that were seeded in the single-user era and leaked
    # owner identity into every user's PULSE feed. Dependent posts, videos, and
    # interaction rows are removed first to satisfy FK constraints.
    # Idempotent: DELETE WHERE is a no-op when the rows are already gone.
    _LEGACY_SLUGS = (
        "maksim-volkov",
        "dr-layla-nasser",
        "felix-bergmann",
        "nora-chen",
        "viktor-ostrowski",
    )
    cur.execute(
        "SELECT id FROM content_creators WHERE user_id IS NULL AND slug = ANY(%s)",
        (_LEGACY_SLUGS,),
    )
    legacy_ids = [r[0] for r in cur.fetchall()]
    if legacy_ids:
        cur.execute(
            "SELECT id FROM content_posts WHERE creator_id = ANY(%s)",
            (legacy_ids,),
        )
        legacy_post_ids = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT id FROM content_videos WHERE creator_id = ANY(%s)",
            (legacy_ids,),
        )
        legacy_video_ids = [r[0] for r in cur.fetchall()]
        if legacy_post_ids:
            cur.execute(
                "DELETE FROM content_interactions WHERE content_type = 'post' AND content_id = ANY(%s)",
                (legacy_post_ids,),
            )
            cur.execute(
                "DELETE FROM content_posts WHERE creator_id = ANY(%s)",
                (legacy_ids,),
            )
        if legacy_video_ids:
            cur.execute(
                "DELETE FROM content_interactions WHERE content_type = 'video' AND content_id = ANY(%s)",
                (legacy_video_ids,),
            )
            cur.execute(
                "DELETE FROM content_videos WHERE creator_id = ANY(%s)",
                (legacy_ids,),
            )
        cur.execute(
            "DELETE FROM content_creators WHERE user_id IS NULL AND slug = ANY(%s)",
            (_LEGACY_SLUGS,),
        )

    conn.commit()
    cur.close()
    conn.close()
