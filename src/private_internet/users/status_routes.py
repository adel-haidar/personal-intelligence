"""User status + admin provisioning endpoints.

Separate router (prefix /api/users and /api/admin) from the auth router so the
auth flow stays self-contained. Status reports the user's provisioning state for
the onboarding UI to poll while the BackgroundTask runs.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from private_internet.core.request_context import (
    RequestContext,
    get_admin_context,
    get_request_context,
)
from private_internet.database import _connect
from private_internet.users.provisioning import provision_user
from private_internet.users.service import get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _count_memories(user_id: str) -> int:
    try:
        from private_internet.memory.service import count_memories

        total, _ = count_memories(user_id=user_id)
        return int(total)
    except Exception:
        return 0


def _has_content(user_id: str) -> bool:
    conn = _connect()
    cur = conn.cursor()
    try:
        # MUST SCOPE BY USER
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM content_posts WHERE user_id = %s)", (user_id,)
        )
        return bool(cur.fetchone()[0])
    except Exception:
        return False
    finally:
        cur.close()
        conn.close()


@router.get("/api/users/me/status")
async def my_status(ctx: RequestContext = Depends(get_request_context)):
    user = get_user_by_id(ctx.user_id)
    if user is None:
        return JSONResponse(status_code=404, content={"error": "User not found."})
    provisioned_at = user.get("provisioned_at")
    return {
        "user_id": ctx.user_id,
        "email_verified": bool(user.get("email_verified")),
        "provisioned": provisioned_at is not None,
        "provisioned_at": provisioned_at,
        "plan": user.get("plan") or "free",
        "onboarding_completed": bool(user.get("onboarding_completed")),
        "memory_count": _count_memories(ctx.user_id),
        "content_ready": _has_content(ctx.user_id),
    }


@router.post("/api/admin/users/{user_id}/reprovision")
async def reprovision(user_id: str, ctx: RequestContext = Depends(get_admin_context)):
    user = get_user_by_id(user_id)
    if user is None:
        return JSONResponse(status_code=404, content={"error": "User not found."})
    await provision_user(dict(user))
    logger.info("[admin] reprovisioned user %s by %s", user_id[:8], ctx.user_id[:8])
    return {"message": "Reprovisioning complete.", "user_id": user_id}
