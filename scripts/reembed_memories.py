"""One-time backfill: re-embed every memory with the self-hosted Ollama model.

Run AFTER Ollama + bge-m3 is provisioned on the host (docs/HANDOFF_ollama_ec2.md)
and BEFORE flipping EMBEDDING_BACKEND=ollama. Existing rows hold Amazon Titan
vectors, which are not comparable to bge-m3 vectors; this rewrites them so
semantic search stays correct after the switch.

It always uses the Ollama embedder regardless of the current EMBEDDING_BACKEND,
so it can run while the app is still serving on Bedrock. By default it only
touches rows not already on the target model (safe to re-run); pass --all to
re-embed unconditionally.

Usage (on the host, in the app venv, from the repo root):
    python scripts/reembed_memories.py          # rows not yet on the target model
    python scripts/reembed_memories.py --all    # every row
"""

import sys

from psycopg2.extras import RealDictCursor

from private_internet.config import get_settings
from private_internet.database import _connect
from private_internet.memory.embeddings import OllamaEmbedder


def main(reembed_all: bool) -> int:
    s = get_settings()
    embedder = OllamaEmbedder(s.embedding_url, s.embedding_model)
    target = embedder.model_id

    conn = _connect()
    read = conn.cursor(cursor_factory=RealDictCursor)
    if reembed_all:
        read.execute("SELECT memory_id, title, content FROM memories")
    else:
        read.execute(
            "SELECT memory_id, title, content FROM memories "
            "WHERE embedding_model IS DISTINCT FROM %s",
            (target,),
        )
    rows = read.fetchall()
    print(f"Re-embedding {len(rows)} memories with {target} via {s.embedding_url} …")

    write = conn.cursor()
    done = 0
    for row in rows:
        vec = embedder.embed(f"{row['title']}\n{row['content']}")
        if len(vec) != embedder.dim:
            print(
                f"  ! {row['memory_id']}: expected {embedder.dim} dims, "
                f"got {len(vec)} — aborting (check the model)."
            )
            conn.rollback()
            return 1
        write.execute(
            "UPDATE memories SET embedding = %s, embedding_model = %s WHERE memory_id = %s",
            (str(vec).replace(" ", ""), target, row["memory_id"]),
        )
        done += 1
        if done % 50 == 0:
            conn.commit()
            print(f"  … {done}/{len(rows)}")

    conn.commit()
    read.close()
    write.close()
    conn.close()
    print(f"Done. Re-embedded {done} memories. Now set EMBEDDING_BACKEND=ollama and restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--all" in sys.argv[1:]))
