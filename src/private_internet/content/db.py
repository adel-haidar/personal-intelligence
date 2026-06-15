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

    conn.commit()
    cur.close()
    conn.close()
