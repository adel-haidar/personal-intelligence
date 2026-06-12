# PHASE 1 — DB Foundation + Creator Seed
## Agent: Claude Code
## Depends on: nothing (first phase)

---

## Goal
Create the PostgreSQL schema for the entire content platform and seed the initial creator personas. All downstream agents depend on these tables existing.

---

## Context
- Repo: `personal-intelligence/`
- ORM: SQLAlchemy (already in use)
- Migration tool: Alembic (already configured)
- DB: RDS PostgreSQL eu-central-1 (existing)
- Existing tables: `memories`, `users`, `oauth_*` — do NOT modify them

---

## Task 1 — New Alembic Migration

Create: `backend/alembic/versions/0004_content_platform.py`

### Tables to create:

```sql
-- AI content creator personas
content_creators (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug VARCHAR(64) UNIQUE NOT NULL,          -- e.g. "maksim-volkov"
  name VARCHAR(128) NOT NULL,
  avatar_url TEXT,
  bio TEXT,
  style_prompt TEXT NOT NULL,               -- injected into generation prompts
  polly_voice_id VARCHAR(64) NOT NULL,      -- e.g. "Maxim", "Joanna"
  polly_language_code VARCHAR(16) NOT NULL, -- e.g. "ru-RU", "en-US"
  topic_affinities TEXT[],                  -- array of topic keywords
  score FLOAT DEFAULT 0.7,                  -- RL score, 0.0–1.0
  total_interactions INT DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
)

-- Topics extracted from MCP memory or detected events
content_topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug VARCHAR(256) UNIQUE NOT NULL,
  source VARCHAR(32) NOT NULL,              -- 'mcp_memory' | 'health' | 'manual' | 'conversation'
  source_ref TEXT,                          -- memory_id, health record id, or null
  weight FLOAT DEFAULT 0.5,                 -- 0.0–1.0, boosted by RL feedback
  used_count INT DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
)

-- Research links attached to a topic
content_research (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  topic_id UUID NOT NULL REFERENCES content_topics(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  title TEXT,
  summary TEXT,                             -- 2–3 sentence AI summary
  fetched_at TIMESTAMPTZ DEFAULT now()
)

-- Social posts (PULSE)
content_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_id UUID NOT NULL REFERENCES content_creators(id),
  topic_id UUID NOT NULL REFERENCES content_topics(id),
  body TEXT NOT NULL,                       -- post text (max ~280 chars or long-form)
  image_url TEXT,                           -- S3/CF URL
  image_prompt TEXT,                        -- stored for reproducibility
  tone VARCHAR(32),                         -- 'critical' | 'supportive' | 'satirical' | 'informative'
  score FLOAT DEFAULT 0.5,
  total_interactions INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
)

-- Videos (SIGNAL)
content_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_id UUID NOT NULL REFERENCES content_creators(id),
  topic_id UUID NOT NULL REFERENCES content_topics(id),
  title TEXT NOT NULL,
  description TEXT,
  script TEXT NOT NULL,                     -- full narration script
  video_url TEXT,                           -- S3/CF URL (null while processing)
  thumbnail_url TEXT,
  duration_seconds INT,
  status VARCHAR(32) DEFAULT 'pending',     -- 'pending' | 'processing' | 'ready' | 'failed'
  score FLOAT DEFAULT 0.5,
  total_interactions INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
)

-- All user interaction events (drives RL)
content_interactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_id UUID NOT NULL,
  content_type VARCHAR(16) NOT NULL,        -- 'post' | 'video'
  action VARCHAR(32) NOT NULL,              -- 'like' | 'dislike' | 'skip' | 'watch_complete' | 'watch_partial' | 'view'
  watch_pct FLOAT,                          -- null for posts; 0.0–1.0 for videos
  created_at TIMESTAMPTZ DEFAULT now()
)
```

### Indexes to add:
```sql
CREATE INDEX idx_posts_creator ON content_posts(creator_id);
CREATE INDEX idx_posts_topic ON content_posts(topic_id);
CREATE INDEX idx_posts_created ON content_posts(created_at DESC);
CREATE INDEX idx_videos_status ON content_videos(status);
CREATE INDEX idx_videos_created ON content_videos(created_at DESC);
CREATE INDEX idx_interactions_content ON content_interactions(content_id, content_type);
CREATE INDEX idx_topics_weight ON content_topics(weight DESC);
```

---

## Task 2 — SQLAlchemy Models

Create: `backend/app/content/models.py`

Use SQLAlchemy 2.0 declarative style (same as existing codebase). Import `Base` from the existing base module.

Models to implement:
- `ContentCreator`
- `ContentTopic`
- `ContentResearch`
- `ContentPost`
- `ContentVideo`
- `ContentInteraction`

All models must have `__tablename__` matching the SQL above.

---

## Task 3 — Creator Seeding Script

Create: `backend/app/content/seed_creators.py`

Seed these 5 creators via a function `seed_default_creators(db: Session)` that is idempotent (check slug before inserting):

### Creator 1 — Maksim Volkov
```python
{
  "slug": "maksim-volkov",
  "name": "Maksim Volkov",
  "bio": "Former Soviet state media editor turned independent analyst. Sees everything through the lens of ideological collapse.",
  "style_prompt": "Write like a dry, sardonic Soviet-era intellectual who is both nostalgic and self-aware. Use short punchy sentences. Reference historical parallels. Never use emojis. Tone: cold irony.",
  "polly_voice_id": "Maxim",
  "polly_language_code": "ru-RU",
  "topic_affinities": ["USSR", "geopolitics", "Europe", "history", "cold war", "socialism"]
}
```

### Creator 2 — Dr. Layla Nasser
```python
{
  "slug": "dr-layla-nasser",
  "name": "Dr. Layla Nasser",
  "bio": "Fintech architect and AI engineering researcher. Zero patience for buzzwords.",
  "style_prompt": "Write like a sharp, no-nonsense technical expert. Dense with insight, sparse with words. Call out hype. Reference real data and standards. Occasionally sarcastic about corporate culture.",
  "polly_voice_id": "Zeina",
  "polly_language_code": "ar-AE",
  "topic_affinities": ["AI", "banking", "certifications", "AWS", "fintech", "machine learning", "career"]
}
```

### Creator 3 — Felix Bergmann
```python
{
  "slug": "felix-bergmann",
  "name": "Felix Bergmann",
  "bio": "German software engineer, startup dreamer, professional complainer about German bureaucracy.",
  "style_prompt": "Write like a frustrated but optimistic German software engineer who is deeply self-aware about his country's contradictions. Mix tech insight with mild existential comedy. Reference Kleinanzeigen, Ämter, and startup culture.",
  "polly_voice_id": "Daniel",
  "polly_language_code": "de-DE",
  "topic_affinities": ["Germany", "startup", "tech jobs", "Switzerland", "let-it-go", "circular economy", "bureaucracy"]
}
```

### Creator 4 — Nora Chen
```python
{
  "slug": "nora-chen",
  "name": "Nora Chen",
  "bio": "Performance coach obsessed with biometrics, body composition, and turning data into results.",
  "style_prompt": "Write like an encouraging but evidence-based fitness coach. Specific about numbers (weight, BF%, macros). Not toxic positivity — real talk. Use short motivational punchlines at the end.",
  "polly_voice_id": "Joanna",
  "polly_language_code": "en-US",
  "topic_affinities": ["gym", "fitness", "weight loss", "Apple Watch", "health metrics", "nutrition", "body composition"]
}
```

### Creator 5 — Viktor Ostrowski
```python
{
  "slug": "viktor-ostrowski",
  "name": "Viktor Ostrowski",
  "bio": "Amateur geopolitical theorist. Finds EU conspiracy in every form he has to fill.",
  "style_prompt": "Write like an Eastern European conspiracy comedy commentator who is always almost right. Paranoid, funny, surprisingly insightful. Mix French expressions occasionally. Never takes himself too seriously.",
  "polly_voice_id": "Mathieu",
  "polly_language_code": "fr-FR",
  "topic_affinities": ["EU", "politics", "Germany", "France", "Switzerland", "migration", "bureaucracy", "Asia"]
}
```

---

## Task 4 — Router Skeleton

Create: `backend/app/content/router.py`

Expose these endpoints (stubs only — implementation comes in later phases):

```python
GET  /api/content/creators         # list active creators
GET  /api/content/posts            # paginated feed, sorted by created_at DESC
GET  /api/content/videos           # paginated video list, sorted by created_at DESC
POST /api/content/interactions     # log an interaction event (body: InteractionEvent schema)
GET  /api/content/topics           # list topics with weights (admin/debug)
```

Register router in `main.py` under prefix `/api/content`.

---

## Task 5 — Pydantic Schemas

Create: `backend/app/content/schemas.py`

```python
class CreatorOut(BaseModel): ...
class TopicOut(BaseModel): ...
class PostOut(BaseModel): ...
class VideoOut(BaseModel): ...
class InteractionEvent(BaseModel):
    content_id: UUID
    content_type: Literal["post", "video"]
    action: Literal["like", "dislike", "skip", "watch_complete", "watch_partial", "view"]
    watch_pct: Optional[float] = None
```

---

## Completion Criteria
- [ ] `alembic upgrade head` runs without errors on existing RDS
- [ ] All 5 creators seeded, visible via `GET /api/content/creators`
- [ ] `/api/content/posts` and `/api/content/videos` return empty arrays (no data yet)
- [ ] `POST /api/content/interactions` accepts valid payload without error
- [ ] No existing endpoints broken
