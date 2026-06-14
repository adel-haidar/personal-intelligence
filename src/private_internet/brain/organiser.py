"""Brain Organiser — three-stage deduplication / clustering / merge workflow.

Per user (multi-tenant: every query is scoped WHERE user_id = ...). All maths is
pure Python (cosine, union-find) — Bedrock is used ONLY to decide/compose merges
for the ambiguous mid-similarity band, with temperature=0 and a forced tool.

Stages:
  1. Near-duplicates  (cosine >= 0.92)  -> union-find groups, merged deterministically
  2. Semantic band    (0.75–0.92)       -> Claude (forced tool) decides should_merge
  3. Commit           -> insert merged memory (re-embedded), soft-delete sources
                         (memories.merged_into), log to brain_organise_runs

Run state lives in a module-level dict (cheap polling); one run per user at a
time. Merges only commit after the new memory is written, so a crash never loses
data — at worst a run is left half-done and sources stay active.
"""

import logging
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from operator import mul

from psycopg2.extras import RealDictCursor

from private_internet.content.llm import bedrock_text_region
from private_internet.database import _connect
from private_internet.memory.service import save_memory, soft_delete_into

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────
NEAR_DUP_THRESHOLD = 0.92      # >= this = near-duplicate (Stage 1, no LLM)
SEMANTIC_LOW = 0.75            # [LOW, NEAR_DUP) = semantic band (Stage 2, LLM)
_DEFAULT_MODEL = "eu.anthropic.claude-3-5-sonnet-20240620-v1:0"

_STAGE_LABELS = {1: "Detecting duplicates", 2: "Clustering", 3: "Merging"}

_MERGE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "should_merge": {"type": "boolean"},
        "merged_content": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["should_merge", "merged_content", "tags", "reason"],
}

# ── Run state (module-level, per user) ────────────────────────────────────────
_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()


class OrganiseAlreadyRunning(Exception):
    pass


def _patch(user_id: str, **fields) -> None:
    with _LOCK:
        if user_id in _RUNS:
            _RUNS[user_id].update(fields)


# ── Pure-Python vector helpers ────────────────────────────────────────────────
def _parse_vec(raw) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    s = str(raw).strip().lstrip("[").rstrip("]")
    if not s:
        return None
    try:
        return [float(x) for x in s.split(",")]
    except ValueError:
        return None


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(map(mul, a, b))  # inputs are pre-normalized -> dot == cosine


# ── Union-Find ────────────────────────────────────────────────────────────────
class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            out.setdefault(self.find(i), []).append(i)
        return out


# ── Data access ───────────────────────────────────────────────────────────────
def _fetch_active(user_id: str) -> list[dict]:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT memory_id, title, content, tags, created_at, embedding
               FROM memories
               WHERE user_id = %s AND merged_into IS NULL AND embedding IS NOT NULL
               ORDER BY created_at""",
            (user_id,),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    out = []
    for r in rows:
        vec = _parse_vec(r["embedding"])
        if not vec:
            continue
        out.append({
            "id": r["memory_id"],
            "title": r["title"] or "",
            "content": r["content"] or "",
            "tags": [t.strip() for t in (r["tags"] or "").split(",") if t.strip()],
            "vec": vec,
        })
    return out


def _count_active(user_id: str) -> int:
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = %s AND merged_into IS NULL",
            (user_id,),
        )
        return cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()


def _insert_run(user_id: str, run_id: str, memories_before: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO brain_organise_runs (id, user_id, memories_before, status)
               VALUES (%s, %s, %s, 'running')""",
            (run_id, user_id, memories_before),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _complete_run(run_id: str, *, status: str, after: int, dups: int, clusters: int) -> dict:
    completed_at = datetime.now(timezone.utc)
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """UPDATE brain_organise_runs
               SET completed_at = %s, memories_after = %s, duplicates_removed = %s,
                   clusters_merged = %s, status = %s
               WHERE id = %s
               RETURNING memories_before, memories_after, duplicates_removed,
                         clusters_merged, completed_at""",
            (completed_at, after, dups, clusters, status, run_id),
        )
        row = cur.fetchone()
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return {
        "memories_before": row["memories_before"],
        "memories_after": row["memories_after"],
        "duplicates_removed": row["duplicates_removed"],
        "clusters_merged": row["clusters_merged"],
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


def _last_run(user_id: str) -> dict | None:
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """SELECT memories_before, memories_after, duplicates_removed,
                      clusters_merged, completed_at
               FROM brain_organise_runs
               WHERE user_id = %s AND status = 'completed'
               ORDER BY completed_at DESC NULLS LAST LIMIT 1""",
            (user_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not row:
        return None
    return {
        "memories_before": row["memories_before"],
        "memories_after": row["memories_after"],
        "duplicates_removed": row["duplicates_removed"],
        "clusters_merged": row["clusters_merged"],
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


# ── Bedrock merge decision (forced tool, temperature 0) ───────────────────────
def _llm_decide_merge(contents: list[str]) -> dict | None:
    import boto3

    model_id = os.getenv("BEDROCK_ORGANISE_MODEL_ID", _DEFAULT_MODEL)
    client = boto3.client("bedrock-runtime", region_name=bedrock_text_region())
    system = (
        "You deduplicate a personal knowledge base. You interpret meaning only — "
        "never invent facts. Given several memory texts that may overlap, decide "
        "whether they describe the same thing and should be merged. If yes, write "
        "one merged_content preserving every distinct fact from all inputs with no "
        "repetition, plus a clean union of tags. If they are about different "
        "things, set should_merge to false."
    )
    user = "Memories:\n\n" + "\n\n---\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contents))
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": user}]}],
        system=[{"text": system}],
        inferenceConfig={"temperature": 0, "maxTokens": 1024},
        toolConfig={
            "tools": [{"toolSpec": {
                "name": "decide_merge",
                "description": "Decide whether the given memories should be merged, and compose the merge.",
                "inputSchema": {"json": _MERGE_TOOL_SCHEMA},
            }}],
            "toolChoice": {"tool": {"name": "decide_merge"}},
        },
    )
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    return None


# ── Merge helpers ─────────────────────────────────────────────────────────────
def _derive_title(merged_content: str, members: list[dict]) -> str:
    longest = max(members, key=lambda m: len(m["content"]), default=None)
    if longest and longest["title"].strip():
        return longest["title"].strip()
    first_line = merged_content.strip().splitlines()[0] if merged_content.strip() else "Merged memory"
    return first_line[:60]


def _commit_merge(user_id: str, members: list[dict], merged_content: str, tags: list[str]) -> None:
    """Insert the merged memory (re-embedded), THEN soft-delete the sources."""
    title = _derive_title(merged_content, members)
    new_memory = save_memory(title=title, content=merged_content, tags=tags, user_id=user_id)
    soft_delete_into([m["id"] for m in members], new_memory.memory_id, user_id=user_id)


def _union_tags(members: list[dict], extra: list[str] | None = None) -> list[str]:
    seen: list[str] = []
    for m in members:
        for t in m["tags"]:
            if t and t not in seen:
                seen.append(t)
    for t in extra or []:
        if t and t not in seen:
            seen.append(t)
    return seen


# ── Core workflow ─────────────────────────────────────────────────────────────
def _run_organise(user_id: str, run_id: str) -> None:
    memories = _fetch_active(user_id)
    memories_before = len(memories)
    n = len(memories)

    if n < 2:
        last = _complete_run(run_id, status="completed", after=memories_before, dups=0, clusters=0)
        _patch(user_id, status="completed", stage=None, stage_label=None, progress_pct=100, last_run=last)
        return

    norm = [_normalize(m["vec"]) for m in memories]

    # ── Stage 1 — near-duplicates (>= NEAR_DUP_THRESHOLD) ─────────────────────
    _patch(user_id, stage=1, stage_label=_STAGE_LABELS[1], progress_pct=5)
    uf_dup = _UnionFind(n)
    sem_edges: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine(norm[i], norm[j])
            if sim >= NEAR_DUP_THRESHOLD:
                uf_dup.union(i, j)
            elif sim >= SEMANTIC_LOW:
                sem_edges.append((i, j))
    dup_groups = [idxs for idxs in uf_dup.groups().values() if len(idxs) >= 2]
    dup_members = {i for g in dup_groups for i in g}
    _patch(user_id, progress_pct=30)

    # ── Stage 2 — semantic band (LLM), excluding Stage-1 members ──────────────
    _patch(user_id, stage=2, stage_label=_STAGE_LABELS[2], progress_pct=35)
    uf_sem = _UnionFind(n)
    for i, j in sem_edges:
        if i in dup_members or j in dup_members:
            continue
        uf_sem.union(i, j)
    sem_groups = [idxs for idxs in uf_sem.groups().values() if len(idxs) >= 2 and not (set(idxs) & dup_members)]

    approved: list[tuple[list[dict], str, list[str]]] = []
    total_sem = len(sem_groups) or 1
    for k, idxs in enumerate(sem_groups):
        members = [memories[i] for i in idxs]
        try:
            decision = _llm_decide_merge([m["content"] for m in members])
        except Exception as e:
            logger.error(f"[user:{user_id[:8]}] merge decision failed: {e}", exc_info=True)
            decision = None
        if decision and decision.get("should_merge") and (decision.get("merged_content") or "").strip():
            tags = _union_tags(members, decision.get("tags") or [])
            approved.append((members, decision["merged_content"].strip(), tags))
        _patch(user_id, progress_pct=35 + int(30 * (k + 1) / total_sem))

    # ── Stage 3 — commit merges ───────────────────────────────────────────────
    _patch(user_id, stage=3, stage_label=_STAGE_LABELS[3], progress_pct=70)
    duplicates_removed = 0
    clusters_merged = 0
    total_commit = (len(dup_groups) + len(approved)) or 1
    done = 0

    # Near-duplicates: deterministic merge (longest content wins; union tags).
    for group in dup_groups:
        members = [memories[i] for i in group]
        canonical = max(members, key=lambda m: len(m["content"]))
        _commit_merge(user_id, members, canonical["content"], _union_tags(members))
        duplicates_removed += len(members)
        done += 1
        _patch(user_id, progress_pct=70 + int(28 * done / total_commit))

    # Semantic merges approved by the model.
    for members, merged_content, tags in approved:
        _commit_merge(user_id, members, merged_content, tags)
        clusters_merged += 1
        done += 1
        _patch(user_id, progress_pct=70 + int(28 * done / total_commit))

    memories_after = _count_active(user_id)
    last = _complete_run(
        run_id, status="completed", after=memories_after,
        dups=duplicates_removed, clusters=clusters_merged,
    )
    _patch(user_id, status="completed", stage=None, stage_label=None, progress_pct=100, last_run=last)
    logger.info(
        f"[user:{user_id[:8]}] organise done — before={memories_before} after={memories_after} "
        f"dups_removed={duplicates_removed} clusters_merged={clusters_merged}"
    )


def _worker(user_id: str, run_id: str) -> None:
    try:
        _run_organise(user_id, run_id)
    except Exception as e:
        logger.error(f"[user:{user_id[:8]}] organise run failed: {e}", exc_info=True)
        try:
            _complete_run(run_id, status="failed", after=_count_active(user_id), dups=0, clusters=0)
        except Exception:
            pass
        _patch(user_id, status="failed", stage=None, stage_label=None, error=str(e))


# ── Public API ────────────────────────────────────────────────────────────────
def start_run(user_id: str) -> str:
    """Begin an organise run for the user. Raises OrganiseAlreadyRunning if one is active."""
    with _LOCK:
        if _RUNS.get(user_id, {}).get("status") == "running":
            raise OrganiseAlreadyRunning()
        run_id = str(uuid.uuid4())
        _RUNS[user_id] = {
            "status": "running",
            "run_id": run_id,
            "stage": 1,
            "stage_label": _STAGE_LABELS[1],
            "progress_pct": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_run": None,
            "error": None,
        }
    try:
        _insert_run(user_id, run_id, _count_active(user_id))
    except Exception:
        logger.exception("Failed to insert brain_organise_runs row")
    threading.Thread(target=_worker, args=(user_id, run_id), daemon=True).start()
    return run_id


def get_status(user_id: str) -> dict:
    """Status payload for polling. Falls back to the DB for last_run when idle."""
    with _LOCK:
        state = dict(_RUNS[user_id]) if user_id in _RUNS else None
    if state and state["status"] == "running":
        return {
            "status": "running",
            "run_id": state["run_id"],
            "stage": state["stage"],
            "stage_label": state["stage_label"],
            "progress_pct": state["progress_pct"],
            "started_at": state["started_at"],
            "last_run": state.get("last_run") or _last_run(user_id),
        }
    # completed / failed (this process) or idle — surface DB last_run either way.
    last = (state.get("last_run") if state else None) or _last_run(user_id)
    return {
        "status": state["status"] if state else "idle",
        "run_id": state["run_id"] if state else None,
        "stage": None,
        "stage_label": None,
        "progress_pct": 100 if state and state["status"] == "completed" else 0,
        "started_at": state["started_at"] if state else None,
        "last_run": last,
    }
