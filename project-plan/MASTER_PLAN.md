# Personal Intelligence — AI Content Platform
## Master Development Plan

> **Project:** personal-intelligence (adel-intelligence)
> **Stack:** Python (FastAPI) + TypeScript (Vue 3) + PostgreSQL + AWS
> **Agent Assignments:** Claude Code · OpenAI Codex · Gemini
> **Goal:** A self-contained AI-driven media platform — social posts and videos auto-generated from topics extracted from the MCP memory brain, with a reinforcement learning feedback loop.

---

## What We Are Building

Two integrated modules inside personal-intelligence:

### 1. `PULSE` — AI Social Feed
A private Twitter/Instagram-like feed where AI-generated **content creators** post text + image content about topics that matter to Adel — extracted live from MCP memory conversations, health data, certifications, job search, and interests.

### 2. `SIGNAL` — AI Video Channel
A private YouTube-like platform where the same creator personas produce **narrated slideshow videos** (script → images → Amazon Polly TTS → FFmpeg assembly). Low cost, fully on AWS.

---

## Core Principles

| Principle | Decision |
|-----------|----------|
| Cost | Target < €15/month for all content generation |
| Video format | Narrated slideshow (FFmpeg + Polly + Bedrock images) — not Runway/Sora |
| Inference | AWS Bedrock (Claude Haiku for text, Nova Canvas for images) |
| Research | Gemini agent with web search grounding |
| Storage | S3 + CloudFront (already established) |
| Auth | Reuse existing OAuth 2.1/PKCE server (port 8002) |
| RL | Interaction signals → creator score → topic weight decay/boost |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   MCP Memory Brain                       │
│  (conversations, health data, career, interests)         │
└────────────────────┬────────────────────────────────────┘
                     │ Topic Extraction (Gemini)
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Topic Intelligence Engine                   │
│  topic_queue → research → score → assign to creator     │
└────────┬────────────────────────┬───────────────────────┘
         │                        │
         ▼                        ▼
┌────────────────┐       ┌────────────────────┐
│  POST Pipeline │       │  VIDEO Pipeline    │
│  (PULSE)       │       │  (SIGNAL)          │
│                │       │                    │
│ Haiku → text   │       │ Haiku → script     │
│ Nova → image   │       │ Nova → 4 images    │
│ S3 → store     │       │ Polly → narration  │
│                │       │ FFmpeg → video     │
│                │       │ S3/CF → deliver    │
└────────┬───────┘       └──────────┬─────────┘
         │                          │
         ▼                          ▼
┌─────────────────────────────────────────────────────────┐
│              Vue 3 Dashboard (dark Soviet aesthetic)     │
│   PULSE feed  │  SIGNAL player  │  Creator profiles     │
└─────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
┌─────────────────────────────────────────────────────────┐
│          Interaction Logger → RL Scoring Engine         │
│  like/dislike/watch% → creator_score → topic_weight     │
└─────────────────────────────────────────────────────────┘
```

---

## Creator Persona System

Creators are **persistent AI personas** — generated once, reused across all content.
Each has: name, avatar (generated), bio, style prompt, Polly voice ID, topic affinities.

**Examples bootstrapped from Adel's interests:**

| Persona | Style | Voice | Topics |
|---------|-------|-------|--------|
| **Maksim Volkov** | Soviet realist commentary, dry irony | Polly `Maxim` (ru-RU) | USSR history, geopolitics, Europe vs Asia |
| **Dr. Layla Nasser** | Sharp fintech analyst, no-BS | Polly `Zeina` (ar-AE) | Banking, certifications, AI engineering |
| **Felix Bergmann** | Sarcastic German tech blogger | Polly `Daniel` (de-DE) | Startup life, Germany frustrations, tech jobs |
| **Nora Chen** | Optimistic health & fitness coach | Polly `Joanna` (en-US) | Gym, weight loss, biometrics, nutrition |
| **Viktor Ostrowski** | Eastern-bloc conspiracy theorist (comedy) | Polly `Mathieu` (fr-FR) | German bureaucracy, EU politics, let-it-go.io |

New creators are spawned when a topic doesn't fit existing personas.
Creators with **score < 0.3** over 30 interactions are **retired**.

---

## Phase Overview

| Phase | Name | Agent | Est. Time | Output |
|-------|------|-------|-----------|--------|
| **P1** | DB Foundation + Creator Seed | Claude Code | 2–3h | Migrations, creator seeding |
| **P2** | Topic Intelligence Engine | Gemini | 3–4h | Topic extractor, research service |
| **P3** | Post Generation Pipeline | Claude Code | 3–4h | End-to-end PULSE post creation |
| **P4** | Video Generation Pipeline | Claude Code | 4–6h | End-to-end SIGNAL video creation |
| **P5** | Frontend — PULSE Feed | Codex | 3–4h | Vue 3 social feed component |
| **P6** | Frontend — SIGNAL Player | Codex | 3–4h | Vue 3 video player component |
| **P7** | RL Scoring Engine | Claude Code | 2–3h | Interaction logger + score updater |
| **P8** | Orchestration + Scheduler | Claude Code | 2–3h | EventBridge + SQS pipeline glue |

**Phases P1 + P2 must complete before P3/P4.**
**Phases P3/P4/P5/P6 can run in parallel.**
**P7 can start alongside P5/P6.**
**P8 is the final integration pass.**

---

## Shared Contracts (all agents must respect)

### Topic object
```json
{
  "id": "uuid",
  "name": "Moving to Singapore vs. staying in Germany",
  "source": "mcp_memory | health | manual",
  "source_ref": "memory_id or null",
  "weight": 0.85,
  "research": [
    { "url": "https://...", "title": "...", "summary": "..." }
  ],
  "created_at": "ISO8601",
  "last_used_at": "ISO8601 | null"
}
```

### Interaction event (sent to RL engine)
```json
{
  "content_id": "uuid",
  "content_type": "post | video",
  "action": "like | dislike | skip | watch_complete | watch_partial",
  "watch_pct": 0.72,
  "timestamp": "ISO8601"
}
```

---

## Repository Integration

All code goes into `personal-intelligence/` repo under:

```
personal-intelligence/
├── backend/
│   ├── app/
│   │   ├── content/          ← new module (P1–P4, P7, P8)
│   │   │   ├── models.py
│   │   │   ├── creators.py
│   │   │   ├── topics.py
│   │   │   ├── posts.py
│   │   │   ├── videos.py
│   │   │   ├── research.py
│   │   │   └── rl.py
│   │   └── ...existing...
│   └── alembic/versions/     ← new migrations
├── frontend/
│   └── src/
│       ├── views/
│       │   ├── PulseFeed.vue     ← P5
│       │   └── SignalPlayer.vue  ← P6
│       └── components/
│           ├── PostCard.vue
│           ├── VideoCard.vue
│           └── CreatorBadge.vue
└── infra/
    └── eventbridge-rules.json   ← P8
```

---

## AWS Services Used

| Service | Purpose | Cost estimate |
|---------|---------|---------------|
| Bedrock (Claude Haiku) | Text generation | ~$0.001/post, ~$0.003/video script |
| Bedrock (Nova Canvas) | Image generation | ~$0.04/image |
| Amazon Polly (Neural) | Video narration | ~$0.016/1000 chars |
| S3 | Asset storage | ~$0.023/GB |
| CloudFront | Video/image CDN | ~$0.01/GB |
| SQS | Pipeline queue | ~free at this scale |
| EventBridge | Cron scheduler | ~free |
| EC2 t3.large (existing) | FFmpeg assembly | $0 additional |
| RDS PostgreSQL (existing) | Metadata | $0 additional |

**Estimated monthly content cost: €5–12 for 20 videos + 60 posts**

---

## See Also
- `agent-tasks/PHASE1_DB_FOUNDATION.md` → Claude Code
- `agent-tasks/PHASE2_TOPIC_INTELLIGENCE.md` → Gemini
- `agent-tasks/PHASE3_POST_GENERATION.md` → Claude Code
- `agent-tasks/PHASE4_VIDEO_PIPELINE.md` → Claude Code
- `agent-tasks/PHASE5_FRONTEND_PULSE.md` → Codex
- `agent-tasks/PHASE6_FRONTEND_SIGNAL.md` → Codex
- `agent-tasks/PHASE7_RL_ENGINE.md` → Claude Code
- `agent-tasks/PHASE8_ORCHESTRATION.md` → Claude Code
- `COST_ANALYSIS.md`
