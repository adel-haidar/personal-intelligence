# When saving information that relates to a topic already stored in memory,
# first call `search` to find the existing memory, then call `update`
# (with append_content=True to add new facts, or field replacement to correct
# old facts) instead of calling `save` to create a duplicate.
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from personal_intelligence.auth.oauth import validate_token as check_token
from personal_intelligence.memory.service import (
    delete_memory,
    fetch_memory,
    init_db,
    save_memory,
    search_memories,
    update_memory,
)

auth_settings = AuthSettings(
    issuer_url="https://adel-intelligence.com",
    resource_server_url="https://adel-intelligence.com",
)

# FastMCP defaults host="127.0.0.1", which auto-enables DNS rebinding protection
# allowing only localhost hosts. Explicitly allow the production domain so requests
# arriving through CloudFront → nginx (Host: adel-intelligence.com) are not rejected
# with 421. Localhost variants are kept for the agents service connecting directly.
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "adel-intelligence.com",
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
    ],
    allowed_origins=[
        "https://adel-intelligence.com",
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


@mcp.tool()
def save(title: str, content: str, tags: list[str] | None = None) -> str:
    """Saving memory with title: {} and tags: {}"""
    memory = save_memory(title, content, tags)
    return f"Saved memory '{memory.title}' with id {memory.memory_id}"


@mcp.tool()
def fetch(memory_id: str) -> str:
    """Fetching Memory with ID '{memory_id}'"""
    memory = fetch_memory(memory_id)
    if memory is None:
        return f"No memory found with ID {memory_id}"
    return f"[{memory.memory_id}] {memory.title}\n{memory.content}\nTags: {', '.join(memory.tags)}"


@mcp.tool()
def search(query: str) -> str:
    """Search memories by keyword. Matches against title, content, and tags."""
    results = search_memories(query)
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
    )
    if memory is None:
        return f"No memory found with ID {memory_id}"
    return f"Updated memory '{memory.title}' (id: {memory.memory_id})"


@mcp.tool()
def delete(memory_id: str, confirm: bool) -> str:
    """Delete a memory permanently. confirm must be True to proceed."""
    if not confirm:
        return "Deletion aborted: confirm must be True to delete a memory."
    deleted = delete_memory(memory_id)
    if not deleted:
        return f"No memory found with ID {memory_id}"
    return f"Deleted memory {memory_id}"


init_db()
