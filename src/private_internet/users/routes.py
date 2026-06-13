"""Email/password user authentication for the multi-tenant platform.

Adjacent to — and deliberately independent of — the OAuth 2.1 server in
``auth/``. Issues platform JWTs (``users/tokens.py``) that ``RequestContext``
resolves to the calling user. Error responses use ``{"error": <message>}`` with
clear, human messages (never a generic "invalid credentials").

Email verification and password reset are gated by ``settings.require_email_verification``
(default False, so the current register→token UX is preserved until SES lands).
The welcome memory is now seeded inside the provisioning BackgroundTask
(users/provisioning.py) so it is written exactly once.
"""

import logging
import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from private_internet.config import get_settings
from private_internet.core.request_context import RequestContext, get_request_context
from private_internet.users.notifications import (
    send_password_reset_email,
    send_verification_email,
)
from private_internet.users.passwords import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)
from private_internet.users.provisioning import provision_user
from private_internet.users.service import (
    clear_reset_token,
    count_users,
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_reset_token,
    get_user_by_verification_token,
    mark_email_verified,
    set_password,
    set_reset_token,
    set_verification_token,
    touch_last_active,
    update_user,
)
from private_internet.users.tokens import create_user_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _error(status: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message}, headers=headers)


# ── In-memory sliding-window rate limiting ──────────────────────────
# Single-process API (uvicorn one worker behind nginx); a per-process dict is
# adequate for abuse mitigation. Keyed by an opaque string (IP or email). NOT a
# security boundary — just throttling. Resets on restart.
_RATE_BUCKETS: dict[str, deque] = defaultdict(deque)


def _rate_limited(key: str, *, limit: int, window_seconds: int) -> int | None:
    """Record a hit for ``key``. Returns None if allowed, else Retry-After seconds."""
    now = time.monotonic()
    bucket = _RATE_BUCKETS[key]
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = int(bucket[0] + window_seconds - now) + 1
        return max(retry_after, 1)
    bucket.append(now)
    return None


def _client_ip(request: Request) -> str:
    # nginx sets X-Forwarded-For; take the first hop. Fall back to the socket.
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RegisterRequest(BaseModel):
    email: str
    display_name: str
    password: str
    referral_source: str | None = None
    plan: str = "free"


class LoginRequest(BaseModel):
    email: str
    password: str


class OnboardingRequest(BaseModel):
    onboarding_step: int | None = None
    onboarding_completed: bool | None = None


class EmailRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request, background: BackgroundTasks):
    settings = get_settings()

    # Per-IP abuse throttle: 5 registrations / hour.
    retry_after = _rate_limited(f"register:{_client_ip(request)}", limit=5, window_seconds=3600)
    if retry_after is not None:
        return _error(
            429,
            "Too many registration attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if not settings.registration_open:
        return _error(403, "Registration is invite-only. Contact the administrator for an account.")
    if settings.max_users and count_users() >= settings.max_users:
        return _error(403, "User limit reached. Contact the administrator for an account.")

    email = body.email.strip().lower()
    display_name = body.display_name.strip()
    if not _EMAIL_RE.match(email):
        return _error(422, "Please enter a valid email address.")
    if not display_name:
        return _error(422, "Display name is required.")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        return _error(422, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    if get_user_by_email(email) is not None:
        return _error(409, "An account with this email already exists.")

    plan = (body.plan or "free").strip().lower() or "free"
    user = create_user(
        email=email,
        display_name=display_name,
        password_hash=hash_password(body.password),
        plan=plan,
        registration_ip=_client_ip(request),
    )

    # Email verification token (stored even when verification is off, so it can
    # be turned on without re-registering existing users).
    token = set_verification_token(user["id"])
    send_verification_email(email, token)

    # Provision in the background — never block (or fail) registration on it.
    background.add_task(provision_user, dict(user))

    logger.info(f"[user:{user['id'][:8]}] registered: {email} (plan={plan})")

    if settings.require_email_verification:
        return JSONResponse(
            status_code=201,
            content={"message": "Verification email sent", "email_verification_required": True},
        )
    return {
        "token": create_user_token(user),
        "user": user,
        "email_verification_required": False,
    }


@router.get("/verify-email")
async def verify_email(token: str = ""):
    settings = get_settings()
    base = settings.base_url

    user = get_user_by_verification_token(token)
    if user is None:
        return RedirectResponse(url=f"{base}/login?verify_error=invalid", status_code=302)

    sent_at = user.get("email_verification_sent_at")
    if sent_at:
        from datetime import datetime, timedelta, timezone

        try:
            sent = datetime.fromisoformat(sent_at)
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - sent > timedelta(hours=settings.verification_token_ttl_hours):
                return RedirectResponse(url=f"{base}/login?verify_error=expired", status_code=302)
        except ValueError:
            pass  # unparseable timestamp → treat as valid rather than locking the user out

    verified = mark_email_verified(user["id"]) or user
    jwt_token = create_user_token(verified)
    logger.info(f"[user:{user['id'][:8]}] email verified")
    return RedirectResponse(
        url=f"{base}/onboarding?token={jwt_token}&verified=1", status_code=302
    )


@router.post("/resend-verification")
async def resend_verification(body: EmailRequest, request: Request):
    """Always 200 — never reveal whether an account exists."""
    email = body.email.strip().lower()
    # 3 / email / hour (and a light per-IP cap to stop enumeration sweeps).
    _rate_limited(f"resend-ip:{_client_ip(request)}", limit=20, window_seconds=3600)
    blocked = _rate_limited(f"resend:{email}", limit=3, window_seconds=3600)

    if blocked is None:
        user = get_user_by_email(email)
        if user is not None and not user.get("email_verified"):
            token = set_verification_token(user["id"])
            send_verification_email(email, token)
            logger.info(f"[user:{user['id'][:8]}] verification email resent")
    return {"message": "If that account exists and is unverified, a new link has been sent."}


@router.post("/forgot-password")
async def forgot_password(body: EmailRequest, request: Request):
    """Always 200 — never reveal whether an account exists."""
    settings = get_settings()
    email = body.email.strip().lower()
    _rate_limited(f"forgot-ip:{_client_ip(request)}", limit=20, window_seconds=3600)
    blocked = _rate_limited(f"forgot:{email}", limit=3, window_seconds=3600)

    if blocked is None:
        user = get_user_by_email(email)
        if user is not None:
            token = set_reset_token(user["id"], settings.reset_token_ttl_hours)
            send_password_reset_email(email, token)
            logger.info(f"[user:{user['id'][:8]}] password reset email sent")
    return {"message": "If that account exists, a password reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    user = get_user_by_reset_token(body.token)
    if user is None:
        return _error(400, "This reset link is invalid or has already been used.")

    expires_at = user.get("password_reset_expires_at")
    if expires_at:
        from datetime import datetime, timezone

        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return _error(400, "This reset link has expired. Request a new one.")
        except ValueError:
            return _error(400, "This reset link is invalid.")

    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        return _error(422, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    set_password(user["id"], hash_password(body.new_password))
    clear_reset_token(user["id"])
    logger.info(f"[user:{user['id'][:8]}] password reset completed")
    return {"message": "Your password has been reset. You can now sign in."}


@router.post("/login")
async def login(body: LoginRequest):
    settings = get_settings()
    email = body.email.strip().lower()
    user = get_user_by_email(email, include_password_hash=True)
    if user is None:
        return _error(404, "No account found with this email.")
    if not verify_password(body.password, user.get("password_hash")):
        return _error(401, "Incorrect password.")

    user.pop("password_hash", None)  # never leaves this layer

    if settings.require_email_verification and not user.get("email_verified"):
        return _error(403, "email_not_verified")

    touch_last_active(user["id"])
    logger.info(f"[user:{user['id'][:8]}] logged in")
    return {"token": create_user_token(user), "user": user}


@router.get("/me")
async def me(ctx: RequestContext = Depends(get_request_context)):
    user = get_user_by_id(ctx.user_id)
    if user is None:
        return _error(404, "User not found.")
    return {"user": user}


@router.patch("/onboarding")
async def update_onboarding(
    body: OnboardingRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return _error(422, "Nothing to update.")
    user = update_user(ctx.user_id, **fields)
    if user is None:
        return _error(404, "User not found.")
    return {"user": user}
