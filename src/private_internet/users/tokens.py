"""JWT session tokens for platform users.

Legacy OAuth bearer tokens (claude.ai MCP, pre-rebrand dashboard sessions)
are still honored by the RequestContext dependency and resolve to the seed
admin user — see core/request_context.py.
"""

import time
import logging

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

# PyJWT is a hard dependency (pyproject), but import it defensively so a missing
# install only disables platform JWT auth instead of crashing the entire API at
# import time — the MCP server, OAuth, memory and content routes must stay up.
try:
    import jwt
except ModuleNotFoundError:  # pragma: no cover
    jwt = None  # type: ignore[assignment]
    logging.getLogger(__name__).error(
        "PyJWT is not installed — platform JWT login/registration is DISABLED. "
        "Run `pip install -e .` (or `pip install pyjwt`). Legacy OAuth is unaffected."
    )

_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def create_user_token(user: dict) -> str:
    if jwt is None:
        raise RuntimeError("PyJWT is not installed — cannot issue user tokens")
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY env var must be set to issue user tokens")
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "is_admin": bool(user.get("is_admin")),
        "plan": user.get("plan") or "free",
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_user_token(token: str) -> dict | None:
    """Return the claims dict, or None if the token is invalid/expired/unsupported."""
    if jwt is None:
        return None
    settings = get_settings()
    if not settings.secret_key:
        return None
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
