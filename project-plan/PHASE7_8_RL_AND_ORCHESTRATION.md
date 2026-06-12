# PHASE 7 — Reinforcement Learning Scoring Engine
## Agent: Claude Code
## Depends on: Phase 1 (interaction table)

---

## Goal
Build a lightweight RL scoring system that processes interaction events and updates creator and topic weights. This closes the feedback loop: what Adel engages with gets made more of; what he skips or dislikes fades out.

---

## Scoring Model

### Interaction → Signal Value

| Action | Signal |
|--------|--------|
| `like` | +0.15 |
| `dislike` | -0.20 |
| `watch_complete` | +0.12 |
| `watch_partial` (watch_pct > 0.7) | +0.08 |
| `watch_partial` (watch_pct 0.3–0.7) | +0.02 |
| `skip` (watch_pct < 0.1) | -0.10 |
| `view` (post viewed, no action) | +0.01 |

### Score Update Formula (Exponential Moving Average)

```python
ALPHA = 0.15  # learning rate — higher = faster adaptation

new_score = (1 - ALPHA) * current_score + ALPHA * (0.5 + signal)
# Clamp to [0.05, 1.0]
new_score = max(0.05, min(1.0, new_score))
```

Starting score for new creators: `0.7` (assume good until proven otherwise).
Starting score for new content: `0.5` (neutral).

---

## Task 1 — Scoring Engine

Create: `backend/app/content/rl.py`

```python
SIGNAL_MAP = {
    "like": 0.15,
    "dislike": -0.20,
    "watch_complete": 0.12,
    "watch_partial": None,   # computed from watch_pct
    "skip": -0.10,
    "view": 0.01
}
ALPHA = 0.15

class RLScoringEngine:
    def compute_signal(self, action: str, watch_pct: float | None) -> float:
        if action == "watch_partial":
            if watch_pct and watch_pct > 0.7:
                return 0.08
            elif watch_pct and watch_pct >= 0.3:
                return 0.02
            else:
                return -0.05
        return SIGNAL_MAP.get(action, 0.0)

    def update_ema(self, current_score: float, signal: float) -> float:
        raw = (1 - ALPHA) * current_score + ALPHA * (0.5 + signal)
        return max(0.05, min(1.0, raw))

    def process_interaction(self, db: Session, event: InteractionEvent) -> None:
        """
        1. Compute signal from action + watch_pct
        2. Update content score (ContentPost or ContentVideo)
        3. Update creator score (via the content's creator_id)
        4. Update topic weight (via the content's topic_id)
        5. Check creator retirement: if creator.score < 0.3 and total_interactions > 20:
               set creator.is_active = False
               log: "Creator {name} retired (score {score})"
        6. Commit all changes in one transaction
        """
```

### Topic Weight Update

```python
def update_topic_weight(self, topic: ContentTopic, signal: float) -> None:
    """
    Topics use a slower learning rate (ALPHA/2) — we want topic preferences
    to be stable over multiple pieces of content, not flip-flop.
    Also boost topic if signal > 0: this topic should be covered again soon.
    If signal < -0.1: increase last_used_at to suppress this topic temporarily.
    """
```

---

## Task 2 — Background Processor

The interaction endpoint in router.py must be **non-blocking**:

```python
@router.post("/interactions")
async def log_interaction(event: InteractionEvent, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 1. Insert raw event into content_interactions (fast)
    db.add(ContentInteraction(...))
    db.commit()
    # 2. Queue score update as background task (non-blocking)
    background_tasks.add_task(rl_engine.process_interaction, db, event)
    return {"status": "logged"}
```

This ensures the frontend gets an instant 200 response while scoring happens async.

---

## Task 3 — Score Dashboard Endpoint

```python
GET /api/content/scores/summary
# Response:
{
  "creators": [
    { "name": str, "slug": str, "score": float, "total_interactions": int, "is_active": bool }
  ],
  "top_topics": [
    { "name": str, "weight": float, "used_count": int }
  ],
  "bottom_topics": [...],
  "retired_creators": [...]
}
```

Useful for observing what the RL system is learning. Display on the existing admin dashboard.

---

## Completion Criteria
- [ ] Like on a post increases that post's score and its creator's score
- [ ] Dislike decreases both
- [ ] Watch complete on a video registers positive signal
- [ ] Skip registers negative signal
- [ ] A creator with score < 0.3 after 20 interactions is marked inactive
- [ ] `GET /api/content/scores/summary` returns real data
- [ ] No score exceeds 1.0 or falls below 0.05

---

---

# PHASE 8 — Orchestration + Scheduler
## Agent: Claude Code
## Depends on: Phases 1–7 complete

---

## Goal
Wire up the automated scheduling so the platform generates content on its own, without manual API calls. EventBridge triggers → SQS → FastAPI worker endpoint.

---

## Architecture

```
EventBridge Rule (cron)
    │
    ▼
SQS Queue: personal-intelligence-content-jobs
    │
    ▼
FastAPI /api/content/jobs/dispatch  (polls or receives via Lambda trigger)
    │
    ├── topic_job.run_topic_intelligence_job()
    ├── post_job.generate_posts_batch()
    └── video_job.generate_videos_batch()
```

---

## Task 1 — Job Dispatcher

Add to router:

```python
POST /api/content/jobs/dispatch
Body: { "job_type": "topics" | "posts" | "videos" | "all" }
Headers: X-Internal-Secret: ...

# Runs the corresponding job as FastAPI background task.
# Returns immediately: { "status": "queued", "job_type": str }
```

---

## Task 2 — EventBridge Rules

Create: `infra/eventbridge-rules.json`

```json
[
  {
    "Name": "pi-content-topics-daily",
    "ScheduleExpression": "cron(0 6 * * ? *)",
    "Description": "Run topic intelligence extraction daily at 6am UTC",
    "Target": {
      "Arn": "arn:aws:sqs:eu-central-1:<ACCOUNT>:personal-intelligence-content-jobs",
      "Input": "{\"job_type\": \"topics\"}"
    }
  },
  {
    "Name": "pi-content-posts-twice-daily",
    "ScheduleExpression": "cron(0 8,20 * * ? *)",
    "Description": "Generate 3 posts at 8am and 8pm UTC",
    "Target": {
      "Arn": "arn:aws:sqs:eu-central-1:<ACCOUNT>:personal-intelligence-content-jobs",
      "Input": "{\"job_type\": \"posts\"}"
    }
  },
  {
    "Name": "pi-content-videos-daily",
    "ScheduleExpression": "cron(0 10 * * ? *)",
    "Description": "Generate 1 video per day at 10am UTC",
    "Target": {
      "Arn": "arn:aws:sqs:eu-central-1:<ACCOUNT>:personal-intelligence-content-jobs",
      "Input": "{\"job_type\": \"videos\"}"
    }
  }
]
```

---

## Task 3 — SQS Poller (or Lambda trigger)

**Option A (simpler — recommended first):** FastAPI startup background task that polls SQS every 60 seconds.

```python
# backend/app/content/jobs/sqs_poller.py

async def poll_sqs_loop():
    """
    Runs as asyncio task in FastAPI lifespan.
    Every 60s: ReceiveMessage from SQS, parse job_type, call dispatcher, delete message.
    """
```

Register in `main.py` lifespan:
```python
asyncio.create_task(poll_sqs_loop())
```

**Option B (production):** Lambda function triggered by SQS that calls the FastAPI dispatch endpoint via internal HTTP. Use this if the app needs to scale beyond one EC2.

Start with Option A.

---

## Task 4 — CLAUDE.md Update

Append to existing `CLAUDE.md`:

```markdown
## Content Platform Jobs

Manual triggers (require INTERNAL_SECRET header):
- POST /api/content/jobs/dispatch {"job_type": "topics"}
- POST /api/content/jobs/dispatch {"job_type": "posts"}
- POST /api/content/jobs/dispatch {"job_type": "videos"}
- POST /api/content/jobs/dispatch {"job_type": "all"}

Automated schedule (UTC):
- Topics: 06:00 daily
- Posts: 08:00 and 20:00 daily (3 posts each run)
- Videos: 10:00 daily (1 video per run)

Monthly content output target: ~60 posts, ~30 videos
```

---

## Task 5 — Health Check Endpoint

```python
GET /api/content/health
# Response:
{
  "status": "ok",
  "pending_videos": int,
  "topics_last_24h": int,
  "posts_last_24h": int,
  "active_creators": int,
  "sqs_connected": bool
}
```

---

## Completion Criteria
- [ ] EventBridge rules created via AWS Console or CLI (script provided)
- [ ] SQS queue `personal-intelligence-content-jobs` created
- [ ] SQS poller running on EC2 startup
- [ ] `dispatch` endpoint correctly routes all 4 job types
- [ ] End-to-end test: send SQS message → topic generated → post generated
- [ ] `/api/content/health` returns correct live stats
- [ ] All jobs survive EC2 restart (poller starts in lifespan)
