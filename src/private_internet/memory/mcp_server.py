# When saving information that relates to a topic already stored in memory,
# first call `search` to find the existing memory, then call `update`
# (with append_content=True to add new facts, or field replacement to correct
# old facts) instead of calling `save` to create a duplicate.
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

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


class PostgresTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        client_id = check_token(token)
        if not client_id:
            return None
        return AccessToken(token=token, client_id=client_id, scopes=[])


mcp = FastMCP(
    "memory",
    token_verifier=PostgresTokenVerifier(),
    auth=auth_settings,
    transport_security=transport_security,
)


def _mcp_user_id() -> str:
    """MCP connections authenticate with legacy OAuth tokens, which carry no
    user identity — they are scoped to the seed admin's brain. Per-user MCP
    access is a future feature."""
    from private_internet.users.service import get_seed_admin_id
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
