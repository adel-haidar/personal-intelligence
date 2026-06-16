# When saving information that relates to a topic already stored in memory,
# first call `search` to find the existing memory, then call `update`
# (with append_content=True to add new facts, or field replacement to correct
# old facts) instead of calling `save` to create a duplicate.
import hmac
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from private_internet.auth.oauth import resolve_token_user
from private_internet.auth.oauth import validate_token as check_token
from private_internet.config import get_settings
from private_internet.memory.service import (
    delete_memory,
    fetch_memory,
    init_db,
    save_memory,
    search_memories,
    update_memory,
)

_settings = get_settings()

auth_settings = AuthSettings(
    issuer_url=_settings.base_url,
    resource_server_url=_settings.base_url,
)

# FastMCP defaults host="127.0.0.1", which auto-enables DNS rebinding protection
# allowing only localhost hosts. Explicitly allow the configured domain so requests
# arriving through CloudFront → nginx (Host: $APP_DOMAIN) are not rejected
# with 421. Localhost variants are kept for the agents service connecting directly.
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        _settings.app_domain,
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
    ],
    allowed_origins=[
        _settings.base_url,
        "http://127.0.0.1",
        "http://127.0.0.1:*",
        "http://localhost",
        "http://localhost:*",
    ],
)


# Sentinel placed in AccessToken.client_id when the caller authenticated with the
# shared INTERNAL_SECRET (same-host agents service). _mcp_user_id() maps this to
# the seed admin — that path MUST NOT change.
_INTERNAL_CLIENT_ID = "internal-service"


class PostgresTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        # Same-host services authenticate with the shared INTERNAL_SECRET — the
        # same credential the REST RequestContext accepts. They scope to the seed
        # admin (see _mcp_user_id), so we leave `subject` unset and tag the
        # client_id with the internal sentinel.
        internal_secret = os.getenv("INTERNAL_SECRET")
        if internal_secret and hmac.compare_digest(token, internal_secret):
            return AccessToken(token=token, client_id=_INTERNAL_CLIENT_ID, scopes=[])
        client_id = check_token(token)
        if not client_id:
            return None
        # Bind the AccessToken to the platform user who authorized this OAuth
        # token (RFC 7662/9068 `sub`). resolve_token_user() returns None for
        # legacy/unbound tokens, in which case _mcp_user_id() falls back to the
        # seed admin so already-connected claude.ai sessions keep working.
        user_id = resolve_token_user(token)
        return AccessToken(
            token=token, client_id=client_id, scopes=[], subject=user_id
        )


mcp = FastMCP(
    "memory",
    token_verifier=PostgresTokenVerifier(),
    auth=auth_settings,
    transport_security=transport_security,
)


def _mcp_user_id() -> str:
    """Resolve the platform user owning the current MCP request's brain.

    Mechanism: FastMCP runs sync @mcp.tool functions inside the same async task
    that handled the request (see func_metadata.call_fn_with_arg_validation —
    sync tools are invoked directly, NOT dispatched to a worker thread), so the
    contextvar set by AuthContextMiddleware is in scope. get_access_token()
    returns the AccessToken our PostgresTokenVerifier.verify_token produced, whose
    `subject` carries the bound platform user_id.

    Resolution order:
    - INTERNAL_SECRET (client_id == internal sentinel) → seed admin. UNCHANGED.
    - OAuth token bound to a user (subject set) → that real user.
    - Legacy/unbound OAuth token (subject None) → seed admin fallback, so
      already-connected claude.ai sessions keep resolving to the owner until
      they re-authorize.
    - No auth context at all → seed admin (defensive; should not happen behind
      the bearer-auth middleware).
    """
    from private_internet.users.service import get_seed_admin_id

    access = get_access_token()
    if access is not None:
        if access.client_id != _INTERNAL_CLIENT_ID and access.subject:
            return access.subject
    return get_seed_admin_id()


@mcp.tool()
def save(title: str, content: str, tags: list[str] | None = None) -> str:
    """Saving memory with title: {} and tags: {}"""
    memory = save_memory(title, content, tags, user_id=_mcp_user_id())
    return f"Saved memory '{memory.title}' with id {memory.memory_id}"


@mcp.tool()
def fetch(memory_id: str) -> str:
    """Fetching Memory with ID '{memory_id}'"""
    memory = fetch_memory(memory_id, user_id=_mcp_user_id())
    if memory is None:
        return f"No memory found with ID {memory_id}"
    return f"[{memory.memory_id}] {memory.title}\n{memory.content}\nTags: {', '.join(memory.tags)}"


@mcp.tool()
def search(query: str) -> str:
    """Search memories by keyword. Matches against title, content, and tags."""
    results = search_memories(query, user_id=_mcp_user_id())
    if not results:
        return f"No memories found for query: {query}"
    lines = [f"- [{m.memory_id}] {m.title}" for m in results]
    return f"Found {len(results)} memories:\n" + "\n".join(lines)


@mcp.tool()
def update(
    memory_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    append_content: bool = False,
) -> str:
    """Update an existing memory. Use append_content=True to append new facts below existing content, or False to replace only the provided fields."""
    memory = update_memory(
        memory_id,
        title=title,
        content=content,
        tags=tags,
        append_content=append_content,
        user_id=_mcp_user_id(),
    )
    if memory is None:
        return f"No memory found with ID {memory_id}"
    return f"Updated memory '{memory.title}' (id: {memory.memory_id})"


@mcp.tool()
def delete(memory_id: str, confirm: bool) -> str:
    """Delete a memory permanently. confirm must be True to proceed."""
    if not confirm:
        return "Deletion aborted: confirm must be True to delete a memory."
    deleted = delete_memory(memory_id, user_id=_mcp_user_id())
    if not deleted:
        return f"No memory found with ID {memory_id}"
    return f"Deleted memory {memory_id}"


init_db()
