import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from psycopg2.extras import RealDictCursor

from private_internet.database import _connect
from private_internet.memory.embeddings import get_embedder

# Every function in this module is tenant-scoped. # MUST SCOPE BY USER
# user_id is required; callers resolve it from RequestContext (API) or the
# seed admin (MCP server, legacy clients).


@dataclass
class Memory:
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    memory_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None


def init_db() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            embedding vector(1024)
        )
    """)
    cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
    # Records which embedding model produced each vector, so a backend switch or
    # model upgrade can detect stale vectors and re-embed (see embeddings.py).
    cur.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_model TEXT")
    # user_id column + backfill is handled by core/tenancy.py at startup.
    conn.commit()
    cur.close()
    conn.close()


def save_memory(
    title: str,
    content: str,
    tags: list[str] | None = None,
    *,
    user_id: str,
) -> Memory:
    assert user_id is not None, "user_id must be set before any memory operation"
    memory_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    tags = tags or []
    text = f"{title}\n{content}"
    embedder = get_embedder()
    embedding = embedder.embed(text)
    embedded_str = str(embedding).replace(" ", "")

    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO memories
               (memory_id, title, content, tags, created_at, embedding, embedding_model, user_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (memory_id, title, content, ",".join(tags), created_at, embedded_str,
         embedder.model_id, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    return Memory(
        memory_id=memory_id,
        title=title,
        content=content,
        tags=tags,
        created_at=created_at,
    )


def fetch_memory(memory_id: str, *, user_id: str) -> Memory | None:
    assert user_id is not None, "user_id must be set before any memory operation"
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM memories WHERE memory_id = %s AND user_id = %s",
        (memory_id, user_id),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return None

    return _row_to_memory(row)


def search_memories(query: str, *, user_id: str, limit: int = 5) -> list[Memory]:
    """Semantic search over memory CONTENT via pgvector cosine distance on the
    brain's embedding (see embeddings.py). Returns the `limit` most
    semantically-relevant memories (full content), NOT a title/tag substring match."""
    assert user_id is not None, "user_id must be set before any memory operation"
    embedding = get_embedder().embed(query)

    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """SELECT *, embedding <=> %s::vector AS distance
           FROM memories
           WHERE user_id = %s AND merged_into IS NULL
           ORDER BY distance
           LIMIT %s""",
        (str(embedding), user_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [_row_to_memory(row) for row in rows]


def count_memories(*, user_id: str) -> tuple[int, datetime | None]:
    """Return (total memories, most recent created/updated timestamp) for a user."""
    assert user_id is not None, "user_id must be set before any memory operation"
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*), MAX(GREATEST(created_at, COALESCE(updated_at, created_at)))
           FROM memories WHERE user_id = %s AND merged_into IS NULL""",
        (user_id,),
    )
    total, last = cur.fetchone()
    cur.close()
    conn.close()
    return total, last


def list_memories(
    page: int = 1,
    page_size: int = 20,
    query: str | None = None,
    *,
    user_id: str,
) -> tuple[list[dict], int]:
    """Return paginated memory rows (id, title, tags, created_at, updated_at, content) and total count."""
    assert user_id is not None, "user_id must be set before any memory operation"
    offset = (page - 1) * page_size

    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if query:
        like = f"%{query}%"
        # Match content as well as title/tags — a document's text matters more
        # than its filename. (Semantic ranking is available via search_memories.)
        cur.execute(
            """SELECT COUNT(*) FROM memories
               WHERE user_id = %s AND merged_into IS NULL
                 AND (title ILIKE %s OR tags ILIKE %s OR content ILIKE %s)""",
            (user_id, like, like, like),
        )
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT memory_id, title, tags, created_at, updated_at, content
               FROM memories
               WHERE user_id = %s AND merged_into IS NULL
                 AND (title ILIKE %s OR tags ILIKE %s OR content ILIKE %s)
               ORDER BY created_at DESC
               LIMIT %s OFFSET %s""",
            (user_id, like, like, like, page_size, offset),
        )
    else:
        cur.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = %s AND merged_into IS NULL",
            (user_id,),
        )
        total = cur.fetchone()["count"]
        cur.execute(
            """SELECT memory_id, title, tags, created_at, updated_at, content
               FROM memories
               WHERE user_id = %s AND merged_into IS NULL
               ORDER BY created_at DESC
               LIMIT %s OFFSET %s""",
            (user_id, page_size, offset),
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    items = [
        {
            "id": row["memory_id"],
            "title": row["title"],
            "tags": [t.strip() for t in row["tags"].split(",") if t.strip()],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "content": row["content"],
        }
        for row in rows
    ]
    return items, total


def update_memory(
    memory_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    append_content: bool = False,
    *,
    user_id: str,
) -> Memory | None:
    assert user_id is not None, "user_id must be set before any memory operation"
    existing = fetch_memory(memory_id, user_id=user_id)
    if existing is None:
        return None

    new_title = title if title is not None else existing.title
    if content is not None and append_content:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        new_content = f"{existing.content}\n\n---\nUpdated {ts}:\n{content}"
    elif content is not None:
        new_content = content
    else:
        new_content = existing.content
    new_tags = tags if tags is not None else existing.tags
    updated_at = datetime.now(timezone.utc)

    conn = _connect()
    cur = conn.cursor()
    if new_title != existing.title or new_content != existing.content:
        embedder = get_embedder()
        embedding = embedder.embed(f"{new_title}\n{new_content}")
        embedded_str = str(embedding).replace(" ", "")
        cur.execute(
            """UPDATE memories
               SET title = %s, content = %s, tags = %s, updated_at = %s,
                   embedding = %s, embedding_model = %s
               WHERE memory_id = %s AND user_id = %s""",
            (new_title, new_content, ",".join(new_tags), updated_at, embedded_str,
             embedder.model_id, memory_id, user_id),
        )
    else:
        cur.execute(
            """UPDATE memories
               SET title = %s, content = %s, tags = %s, updated_at = %s
               WHERE memory_id = %s AND user_id = %s""",
            (new_title, new_content, ",".join(new_tags), updated_at, memory_id, user_id),
        )
    conn.commit()
    cur.close()
    conn.close()

    return Memory(
        memory_id=memory_id,
        title=new_title,
        content=new_content,
        tags=new_tags,
        created_at=existing.created_at,
        updated_at=updated_at,
    )


def soft_delete_into(source_ids: list[str], target_id: str, *, user_id: str) -> int:
    """Mark `source_ids` as merged into `target_id` (Brain Organiser soft-delete).

    Never hard-deletes: the rows stay, but `merged_into` excludes them from every
    user-facing read. Returns the number of rows updated."""
    assert user_id is not None, "user_id must be set before any memory operation"
    if not source_ids:
        return 0
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE memories SET merged_into = %s WHERE memory_id = ANY(%s) AND user_id = %s",
        (target_id, list(source_ids), user_id),
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return updated


def delete_memory(memory_id: str, *, user_id: str) -> bool:
    assert user_id is not None, "user_id must be set before any memory operation"
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM memories WHERE memory_id = %s AND user_id = %s",
        (memory_id, user_id),
    )
    deleted = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return deleted


def delete_all_memories(*, user_id: str) -> int:
    """'Clear my brain' — remove every memory for a user. Returns count removed."""
    assert user_id is not None, "user_id must be set before any memory operation"
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM memories WHERE user_id = %s", (user_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return deleted


def _row_to_memory(row: Mapping[str, Any]) -> Memory:
    tags_raw = row["tags"]
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    return Memory(
        memory_id=row["memory_id"],
        title=row["title"],
        content=row["content"],
        tags=tags,
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
    )
