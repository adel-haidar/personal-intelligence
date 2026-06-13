"""JWT session tokens for platform users.

Legacy OAuth bearer tokens (claude.ai MCP, pre-rebrand dashboard sessions)
are still honored by the RequestContext dependency and resolve to the seed
admin user — see core/request_context.py.
"""

import time
import logging

import jwt

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def create_user_token(user: dict) -> str:
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY env var must be set to issue user tokens")
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "is_admin": bool(user.get("is_admin")),
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_user_token(token: str) -> dict | None:
    """Return the claims dict, or None if the token is invalid/expired."""
    settings = get_settings()
    if not settings.secret_key:
        return None
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
