"""Run content/intelligence jobs across all active users."""

import logging
from typing import Any, Awaitable, Callable

from private_internet.users.service import list_onboarded_user_ids

logger = logging.getLogger(__name__)


async def run_for_all_users(
    job_fn: Callable[..., Awaitable[Any]],
    **job_kwargs,
) -> dict:
    """
    Invoke `job_fn(user_id=..., **job_kwargs)` once per onboarded user.
    One user's failure never breaks the others.
    """
    user_ids = list_onboarded_user_ids()
    succeeded = 0
    failed = 0
    for user_id in user_ids:
        try:
            await job_fn(user_id=user_id, **job_kwargs)
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.error(f"[user:{user_id[:8]}] Job {job_fn.__name__} failed: {e}", exc_info=True)
            continue  # never let one user's failure break others
    logger.info(
        f"run_for_all_users({job_fn.__name__}) — {succeeded} succeeded, {failed} failed, "
        f"{len(user_ids)} users total"
    )
    return {"users": len(user_ids), "succeeded": succeeded, "failed": failed}
