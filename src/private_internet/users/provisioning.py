"""Per-user provisioning pipeline (Phase 3).

Runs as a FastAPI BackgroundTask immediately after registration — the user never
waits for it. There is NO SQS/EventBridge in this deployment; this is a plain
async function.

Hard rule: provisioning failure must NEVER affect registration. Every step is
best-effort and wrapped so a failure logs and continues; ``provision_user`` never
raises. The whole pipeline is idempotent and safe to re-run (admin reprovision).

"Provisioning" here means, for a brand-new user:
  1. S3 folder markers under ``{user_id}/`` (best-effort, skipped if no bucket).
  2. A welcome memory seeded into their private brain.
  3. Subscriptions to the shared content creators (user_creator_preferences).
  4. A few bootstrap topics + an initial batch of posts and one video so the
     feed isn't empty on first login.
  5. ``users.provisioned_at`` stamped.
"""

import logging
import os
import uuid

from private_internet.database import _connect

logger = logging.getLogger(__name__)


def _log_prefix(user_id: str) -> str:
    return f"[user:{user_id[:8]}]"


def _create_s3_structure(user_id: str) -> None:
    """Create zero-byte prefix markers so the user's folders exist in the
    bucket. Skipped gracefully if S3_CONTENT_BUCKET is unset or boto3/creds are
    unavailable."""
    bucket = os.getenv("S3_CONTENT_BUCKET")
    if not bucket:
        logger.info("%s S3_CONTENT_BUCKET unset — skipping S3 structure", _log_prefix(user_id))
        return
    try:
        import boto3

        from private_internet.config import get_settings

        s3 = boto3.client("s3", region_name=get_settings().aws_region)
        for sub in ("posts", "videos", "health", "uploads", "tmp"):
            s3.put_object(Bucket=bucket, Key=f"{user_id}/{sub}/", Body=b"")
        logger.info("%s S3 folder structure created in %s", _log_prefix(user_id), bucket)
    except Exception as e:
        logger.warning("%s S3 structure skipped: %s", _log_prefix(user_id), e)


def _seed_memory(user: dict) -> None:
    """Seed the user's brain with a first memory. Non-fatal (Bedrock embedding
    may hiccup). Idempotent enough — re-running just adds another intro memory,
    which is harmless, so we guard on provisioned_at at the caller for re-runs."""
    from private_internet.memory.service import save_memory

    user_id = str(user["id"])
    display_name = user.get("display_name") or user.get("email", "")
    content = (
        f"User registered. Display name: {display_name}. Email: {user.get('email')}."
    )
    try:
        save_memory(
            title="Account created",
            content=content,
            tags=["introduction", "onboarding", "profile"],
            user_id=user_id,
        )
        logger.info("%s welcome memory seeded", _log_prefix(user_id))
    except Exception as e:
        logger.warning("%s welcome memory not saved: %s", _log_prefix(user_id), e)


def _assign_content_creators(user_id: str) -> None:
    """Subscribe the user to every active shared creator, idempotently."""
    from private_internet.content.creators import list_creators

    try:
        creators = list_creators(active_only=True)
    except Exception as e:
        logger.warning("%s could not list creators: %s", _log_prefix(user_id), e)
        return

    conn = _connect()
    cur = conn.cursor()
    try:
        for creator in creators:
            cur.execute(
                """INSERT INTO user_creator_preferences (user_id, creator_id, weight, is_enabled)
                   VALUES (%s, %s, 1.0, TRUE)
                   ON CONFLICT (user_id, creator_id) DO NOTHING""",
                (user_id, creator["id"]),
            )
        conn.commit()
        logger.info("%s subscribed to %d creators", _log_prefix(user_id), len(creators))
    except Exception as e:
        conn.rollback()
        logger.warning("%s creator assignment failed: %s", _log_prefix(user_id), e)
    finally:
        cur.close()
        conn.close()


# Default seed topics so the very first feed has something to generate from.
# content_topics.id is TEXT and slug is unique per (user_id, slug) post-migration.
_BOOTSTRAP_TOPICS = [
    ("Getting started with Private Internet", "getting-started"),
    ("Your private AI brain", "private-ai-brain"),
    ("Ideas worth remembering", "ideas-worth-remembering"),
]


def _ensure_bootstrap_topics(user_id: str) -> int:
    """Insert default topics for the user (source='bootstrap'), idempotent on the
    per-user slug unique constraint. Returns how many topics the user now has."""
    conn = _connect()
    cur = conn.cursor()
    created = 0
    try:
        for name, slug in _BOOTSTRAP_TOPICS:
            cur.execute(
                """INSERT INTO content_topics (id, name, slug, source, weight, user_id)
                   VALUES (%s, %s, %s, 'bootstrap', 0.8, %s)
                   ON CONFLICT (user_id, slug) DO NOTHING""",
                (str(uuid.uuid4()), name, slug, user_id),
            )
            created += cur.rowcount or 0
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning("%s bootstrap topics failed: %s", _log_prefix(user_id), e)
    finally:
        cur.close()
        conn.close()
    return created


async def _generate_bootstrap_content(user_id: str) -> None:
    """Seed topics, then generate a small initial batch of posts + one video.
    Posts depend on topics existing first. Best-effort: Bedrock/content failures
    log and continue (the feed simply fills in on the next scheduled run)."""
    _ensure_bootstrap_topics(user_id)

    try:
        from private_internet.content.jobs.post_job import generate_posts_batch

        await generate_posts_batch(count=3, user_id=user_id)
    except Exception as e:
        logger.warning("%s bootstrap posts failed: %s", _log_prefix(user_id), e)

    try:
        from private_internet.content.jobs.video_job import generate_video

        await generate_video(user_id=user_id)
    except Exception as e:
        logger.warning("%s bootstrap video failed: %s", _log_prefix(user_id), e)


def _mark_provisioned(user_id: str) -> None:
    from private_internet.users.service import update_user
    from datetime import datetime, timezone

    try:
        update_user(user_id, provisioned_at=datetime.now(timezone.utc))
        logger.info("%s provisioned_at stamped", _log_prefix(user_id))
    except Exception as e:
        logger.warning("%s could not stamp provisioned_at: %s", _log_prefix(user_id), e)


async def provision_user(user: dict) -> None:
    """Full provisioning pipeline. Safe to re-run. Never raises."""
    user_id = str(user["id"])
    logger.info("%s provisioning started", _log_prefix(user_id))
    try:
        _create_s3_structure(user_id)
        _seed_memory(user)
        _assign_content_creators(user_id)
        await _generate_bootstrap_content(user_id)
        _mark_provisioned(user_id)
        logger.info("%s provisioning complete", _log_prefix(user_id))
    except Exception:
        # Defensive catch-all — individual steps already swallow their errors,
        # but provisioning must never bubble up to the caller / registration.
        logger.exception("%s provisioning failed", _log_prefix(user_id))
