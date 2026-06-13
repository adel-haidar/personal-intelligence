"""Per-request user context for multi-tenant data isolation.

Every endpoint that reads or writes user data MUST take
`ctx: RequestContext = Depends(get_request_context)` and scope its queries
with `WHERE user_id = ctx.user_id`.  # MUST SCOPE BY USER

Two bearer token types are honored:
- Platform JWTs (users/tokens.py) → the token's own user.
- Legacy OAuth 2.1 tokens (claude.ai MCP connector and pre-rebrand dashboard
  sessions) → the seed admin user. Per-user MCP access is a future feature.
"""

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request

from private_internet.auth.oauth import validate_token
from private_internet.users.service import get_seed_admin_id, get_user_by_id
from private_internet.users.tokens import decode_user_token

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    user_id: str
    user_email: str
    is_admin: bool

    @property
    def log_prefix(self) -> str:
        return f"[user:{self.user_id[:8]}]"


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    return auth[7:]


async def get_request_context(request: Request) -> RequestContext:
    token = _bearer_token(request)

    # Platform JWT
    claims = decode_user_token(token)
    if claims is not None:
        return RequestContext(
            user_id=str(claims["sub"]),
            user_email=claims.get("email", ""),
            is_admin=bool(claims.get("is_admin")),
        )

    # Legacy OAuth token → seed admin
    client_id = validate_token(token)
    if client_id:
        admin_id = get_seed_admin_id()
        admin = get_user_by_id(admin_id)
        return RequestContext(
            user_id=admin_id,
            user_email=admin["email"] if admin else "",
            is_admin=True,
        )

    raise HTTPException(status_code=401, detail="invalid token")


async def get_admin_context(request: Request) -> RequestContext:
    """Like get_request_context, but rejects non-admin users."""
    ctx = await get_request_context(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin access required")
    return ctx
