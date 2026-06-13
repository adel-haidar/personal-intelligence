# PHASE 3 — Per-User Provisioning Pipeline
## Agent: Claude Code
## Depends on: Phase 2 (user record must exist)

---

## Goal
Every time a new user is created, automatically set up their private namespace across all services. This runs as an async pipeline triggered by registration — the user never waits for it.

---

## What "Provisioning" Means

No new AWS resources are created per user. Provisioning means:

1. S3 folder structure created under `{user_id}/`
2. MCP memory namespace initialised
3. Default content creator assignments recorded
4. Welcome sequence queued
5. Initial content generation job queued (so the feed isn't empty on first login)

Total time: under 3 seconds.

---

## Task 1 — Provisioning Service

Create: `backend/app/users/provisioning.py`

```python
class UserProvisioningService:

    async def provision(self, user: User, db: Session) -> None:
        """
        Full provisioning pipeline. Called as a FastAPI background task
        immediately after registration. Never blocks the registration response.
        """
        try:
            await self._create_s3_structure(user.id)
            await self._init_memory_namespace(user)
            await self._assign_content_creators(user.id, db)
            await self._queue_initial_content_job(user.id)
            await self._mark_provisioned(user.id, db)
        except Exception as e:
            log.error(f"[user:{str(user.id)[:8]}] Provisioning failed: {e}")
            # Do NOT raise — provisioning failure must not affect registration
            # Log to CloudWatch and continue

    async def _create_s3_structure(self, user_id: UUID) -> None:
        """
        Create placeholder objects to establish the user's folder structure.
        S3 doesn't have real folders — a zero-byte object with a trailing slash
        is the convention.
        """
        s3 = boto3.client('s3')
        prefixes = [
            f"{user_id}/posts/",
            f"{user_id}/videos/",
            f"{user_id}/health/",
            f"{user_id}/uploads/",
            f"{user_id}/tmp/",
        ]
        for prefix in prefixes:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=prefix,
                Body=b'',
                ContentLength=0,
            )

    async def _init_memory_namespace(self, user: User) -> None:
        """
        Save a seed memory entry that gives the AI context about who this is.
        This is the system-level bootstrap — the user's own intro comes from onboarding.
        """
        seed = (
            f"New user registered. "
            f"Display name: {user.display_name}. "
            f"Email: {user.email}. "
            f"Plan: {user.plan}. "
            f"Registration date: {user.created_at.isoformat()}. "
            f"Onboarding not yet completed."
        )
        # Call existing MCP memory save endpoint scoped to this user
        await save_memory(
            content=seed,
            tags=["system", "registration", "bootstrap"],
            user_id=user.id,
        )

    async def _assign_content_creators(self, user_id: UUID, db: Session) -> None:
        """
        Record which global content creators are active for this user.
        All 5 default creators are assigned at full weight.
        Stored in user_creator_preferences table (see migration below).
        """
        creators = db.query(ContentCreator).filter(ContentCreator.is_active == True).all()
        for creator in creators:
            pref = UserCreatorPreference(
                user_id=user_id,
                creator_id=creator.id,
                weight=1.0,
                is_enabled=True,
            )
            db.add(pref)
        db.commit()

    async def _queue_initial_content_job(self, user_id: UUID) -> None:
        """
        Queue a 'bootstrap' job that generates:
        - 3 posts (one per top-weight default topic)
        - 1 video
        This ensures the feed is not empty when the user finishes onboarding.
        Default topics are generic enough to work before the user adds memories.
        """
        sqs = boto3.client('sqs')
        sqs.send_message(
            QueueUrl=CONTENT_JOB_QUEUE_URL,
            MessageBody=json.dumps({
                "job_type": "bootstrap",
                "user_id": str(user_id),
                "posts_count": 3,
                "videos_count": 1,
            }),
        )

    async def _mark_provisioned(self, user_id: UUID, db: Session) -> None:
        db.query(User).filter(User.id == user_id).update({
            "provisioned_at": datetime.utcnow()
        })
        db.commit()
```

---

## Task 2 — Migration: User Creator Preferences

Add to migration `0006_saas_users.py` or create `0007_user_creator_prefs.py`:

```sql
CREATE TABLE user_creator_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  creator_id UUID NOT NULL REFERENCES content_creators(id) ON DELETE CASCADE,
  weight FLOAT DEFAULT 1.0,      -- RL can reduce this if user dislikes this creator
  is_enabled BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, creator_id)
);

-- Add provisioned_at to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS provisioned_at TIMESTAMPTZ;
```

---

## Task 3 — Bootstrap Content Job

In `backend/app/content/jobs/post_job.py`, add:

```python
async def generate_bootstrap_content(user_id: UUID, db: Session, posts_count: int = 3, videos_count: int = 1):
    """
    Generates initial content for a new user before they've added any memories.
    Uses a small set of default topics that are broad enough to be relevant to anyone.
    """
    DEFAULT_BOOTSTRAP_TOPICS = [
        "Getting started with personal AI and data ownership",
        "How AI is changing personal productivity in 2026",
        "The value of knowing your own health and financial data",
    ]

    for topic_name in DEFAULT_BOOTSTRAP_TOPICS[:posts_count]:
        # Create a temporary topic record for this user
        topic = ContentTopic(
            user_id=user_id,
            name=topic_name,
            slug=slugify(topic_name),
            source="bootstrap",
            weight=0.5,
        )
        db.add(topic)
        db.flush()
        await generate_post(db=db, user_id=user_id, topic_id=topic.id)

    if videos_count > 0:
        await generate_video(db=db, user_id=user_id)

    log.info(f"[user:{str(user_id)[:8]}] Bootstrap content generated")
```

---

## Task 4 — SQS Consumer: Provisioning Queue

The existing SQS poller (`sqs_poller.py`) must handle the `bootstrap` job type:

```python
async def dispatch_job(message: dict):
    job_type = message.get("job_type")
    user_id = message.get("user_id")

    if job_type == "bootstrap" and user_id:
        await generate_bootstrap_content(
            user_id=UUID(user_id),
            db=next(get_db()),
            posts_count=message.get("posts_count", 3),
            videos_count=message.get("videos_count", 1),
        )
    elif job_type == "topics":
        await run_for_all_users(run_topic_intelligence_job)
    elif job_type == "posts":
        await run_for_all_users(generate_posts_batch)
    elif job_type == "videos":
        await run_for_all_users(generate_videos_batch)
```

---

## Task 5 — Admin Endpoint: Manual Re-Provision

For support use — if provisioning failed silently:

```python
POST /api/admin/users/{user_id}/reprovision
Headers: X-Internal-Secret: ...

# Re-runs the full provisioning pipeline for a user.
# Safe to run multiple times (idempotent — checks before creating).
```

---

## Task 6 — Provisioning Status Endpoint

```python
GET /api/users/me/status
# Response:
{
  "user_id": "uuid",
  "email_verified": true,
  "provisioned": true,
  "provisioned_at": "ISO8601",
  "plan": "free",
  "onboarding_completed": false,
  "memory_count": 1,
  "content_ready": false   # true once bootstrap job completes
}
```

Frontend polls this every 5 seconds during onboarding until `content_ready: true`, then shows the "Your first posts are ready" message.

---

## Completion Criteria
- [ ] Registration triggers provisioning automatically within 1 second
- [ ] S3 folder structure exists for new user after registration
- [ ] Seed memory entry created with correct user_id
- [ ] All 5 default creators assigned in `user_creator_preferences`
- [ ] Bootstrap SQS job enqueued and processed
- [ ] 3 posts and 1 video exist for new user within 5 minutes of registration
- [ ] Provisioning failure does not break registration (silent failure + logging)
- [ ] `GET /api/users/me/status` returns accurate state
- [ ] Re-provision endpoint is idempotent
