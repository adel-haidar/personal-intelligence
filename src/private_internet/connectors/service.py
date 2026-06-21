"""Connector orchestration service.

Handles:
  - OAuth state (signed with SECRET_KEY via HMAC — mirrors the google_auth cookie
    pattern but uses a DB-free approach suitable for stateless OAuth callbacks).
  - Token CRUD (delegates to db.py).
  - Background import runs (threading, mirrors brain/organiser.py pattern).
  - Chunking and save_memory calls (mirrors memory/routes.py _chunk_text).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timezone

from private_internet.connectors.base import Credentials
from private_internet.connectors.db import (
    count_imported_items,
    delete_account,
    get_account,
    is_item_imported,
    record_item,
    save_account,
    update_account_status,
)
from private_internet.connectors.registry import get_connector
from private_internet.memory.service import save_memory

logger = logging.getLogger(__name__)

# ── Import run state (module-level, per (user_id, connector_id)) ──────────────
# Key: f"{user_id}:{connector_id}"
_RUNS: dict[str, dict] = {}
_LOCK = threading.Lock()

# Maximum items imported per run to avoid runaway embedding cost.
_MAX_ITEMS_PER_RUN = 200

# Chunk size mirrors memory/routes.py _PDF_CHUNK_SIZE (4 KB per chunk).
_CHUNK_SIZE = 4000


# ── State helpers ──────────────────────────────────────────────────────────────

def _run_key(connector_id: str, user_id: str) -> str:
    return f"{user_id}:{connector_id}"


def _patch_run(connector_id: str, user_id: str, **fields) -> None:
    key = _run_key(connector_id, user_id)
    with _LOCK:
        if key in _RUNS:
            _RUNS[key].update(fields)


# ── OAuth state helpers ────────────────────────────────────────────────────────

def _get_secret() -> str:
    """Return the app SECRET_KEY; falls back to a weak constant if unset
    (which is already logged as a warning at startup)."""
    from private_internet.config import get_settings
    return get_settings().secret_key or "insecure-fallback-set-secret-key"


def build_state(connector_id: str, user_id: str) -> str:
    """Build a signed state token encoding user_id and connector_id.

    Format: base64url(JSON payload) + "." + HMAC-SHA256(payload, secret)
    This is stateless — no DB row needed — yet unforgeable as long as SECRET_KEY
    is set. The callback validates the HMAC before trusting the payload.
    """
    import base64
    payload = json.dumps({"c": connector_id, "u": user_id}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(
        _get_secret().encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_state(state: str) -> tuple[str, str] | None:
    """Verify and decode the state token. Returns (connector_id, user_id) or None."""
    import base64
    try:
        payload_b64, sig = state.rsplit(".", 1)
        expected = hmac.new(
            _get_secret().encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        # Restore base64 padding.
        pad = 4 - len(payload_b64) % 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * pad))
        return payload["c"], payload["u"]
    except Exception:
        return None


# ── Public API — OAuth flow ────────────────────────────────────────────────────

def build_authorize(connector_id: str, user_id: str) -> str:
    """Build the provider authorize URL with a signed state parameter."""
    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"Unknown connector: {connector_id}")
    state = build_state(connector_id, user_id)
    return connector.authorize_url(state)


def handle_callback(connector_id: str, code: str, state: str) -> str:
    """Validate state, exchange code, persist credentials, kick off import.

    Returns the resolved user_id so the route can build the redirect URL.
    Raises ValueError on any validation failure.
    """
    decoded = verify_state(state)
    if decoded is None:
        raise ValueError("Invalid or tampered state parameter")
    state_connector_id, user_id = decoded
    if state_connector_id != connector_id:
        raise ValueError("State connector mismatch")

    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"Unknown connector: {connector_id}")

    creds: Credentials = connector.exchange_code(code)
    save_account(
        connector_id=connector_id,
        user_id=user_id,
        access_token=creds.access_token,
        refresh_token=creds.refresh_token,
        expiry=creds.expiry,
        scopes=creds.scopes,
        external_account=creds.external_account,
        status="connected",
    )
    logger.info("[connector:%s] [user:%s] connected", connector_id, user_id[:8])

    # Kick off the initial import in a background thread (mirrors brain/organiser).
    _start_import(connector_id, user_id)
    return user_id


# ── Chunking (mirrors memory/routes.py _chunk_text) ──────────────────────────

def _chunk_text(text: str) -> list[str]:
    if len(text) <= _CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= _CHUNK_SIZE:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, _CHUNK_SIZE)
        if split_at <= 0:
            split_at = _CHUNK_SIZE
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return chunks


# ── File persistence (mirrors memory/routes.py _save_uploaded_file) ──────────

def _save_binary(user_id: str, filename: str, data: bytes) -> str:
    """Persist an imported file's original bytes to the user's upload dir using
    the same `{sha256[:12]}_{filename}` naming as POST /api/file, so the job-hunt
    agent's document discovery (which globs that dir + matches by filename) picks
    it up and can merge the original into an application. Returns the disk path."""
    from private_internet.config import get_settings

    user_dir = os.path.join(get_settings().upload_dir, user_id)
    os.makedirs(user_dir, exist_ok=True)
    file_hash = hashlib.sha256(data).hexdigest()[:12]
    path = os.path.join(user_dir, f"{file_hash}_{filename}")
    with open(path, "wb") as f:
        f.write(data)
    return path


# ── Background import ─────────────────────────────────────────────────────────

def _run_import(connector_id: str, user_id: str) -> None:
    """Fetch all pages from the connector and save new items to memory.

    - Skips items already in connector_items (deduplication).
    - Chunks long content (mirrors memory/routes.py).
    - Saves via save_memory (embeds + pgvector).
    - Per-item try/except so one bad item doesn't abort the run.
    - Caps at _MAX_ITEMS_PER_RUN to control Bedrock embedding cost.
    """
    connector = get_connector(connector_id)
    if connector is None:
        logger.error("[connector:%s] unknown connector in _run_import", connector_id)
        return

    account = get_account(connector_id, user_id)
    if account is None:
        logger.error("[connector:%s] [user:%s] no account found", connector_id, user_id[:8])
        return

    # Build Credentials from the stored account row.
    creds = Credentials(
        access_token=account["access_token"],
        refresh_token=account.get("refresh_token"),
        expiry=account.get("expiry"),
        scopes=account.get("scopes"),
        external_account=account.get("external_account"),
    )

    update_account_status(connector_id, user_id, status="syncing")
    _patch_run(connector_id, user_id, status="running")

    total_imported = 0
    cursor: str | None = None
    try:
        while total_imported < _MAX_ITEMS_PER_RUN:
            try:
                page = connector.fetch_items(creds, cursor)
            except Exception as exc:
                logger.error(
                    "[connector:%s] [user:%s] fetch_items failed (cursor=%s): %s",
                    connector_id, user_id[:8], cursor, exc,
                )
                break

            for item in page.items:
                if total_imported >= _MAX_ITEMS_PER_RUN:
                    break
                if is_item_imported(connector_id, item.external_id, user_id):
                    continue

                # File-backed items (e.g. a Drive CV PDF): persist the original
                # bytes to disk and tag the memory `file-upload` so the job-hunt
                # agent finds + attaches it. The memory title must be the bare
                # filename so the agent's filename-based disk match works.
                tags = ["connector", connector_id]
                title_base = item.title
                if item.raw_bytes and item.filename:
                    try:
                        _save_binary(user_id, item.filename, item.raw_bytes)
                        title_base = item.filename
                        ext = (
                            item.filename.rsplit(".", 1)[-1].lower()
                            if "." in item.filename else ""
                        )
                        tags = ["connector", connector_id, "file-upload"]
                        if ext:
                            tags.append(ext)
                    except Exception as exc:
                        logger.warning(
                            "[connector:%s] [user:%s] failed to persist binary for %s: %s",
                            connector_id, user_id[:8], item.external_id, exc,
                        )

                chunks = _chunk_text(item.content)
                total_chunks = len(chunks)
                first_memory_id: str | None = None
                for i, chunk in enumerate(chunks):
                    title = title_base if total_chunks == 1 else f"{title_base} ({i + 1}/{total_chunks})"
                    try:
                        mem = save_memory(
                            title=title,
                            content=chunk,
                            tags=tags,
                            user_id=user_id,
                        )
                        if first_memory_id is None:
                            first_memory_id = mem.memory_id
                    except Exception as exc:
                        logger.warning(
                            "[connector:%s] [user:%s] save_memory failed for %s chunk %d: %s",
                            connector_id, user_id[:8], item.external_id, i, exc,
                        )
                if first_memory_id is not None:
                    try:
                        record_item(connector_id, item.external_id, first_memory_id, user_id)
                    except Exception as exc:
                        logger.warning(
                            "[connector:%s] [user:%s] record_item failed for %s: %s",
                            connector_id, user_id[:8], item.external_id, exc,
                        )
                    total_imported += 1

            cursor = page.next_cursor
            if cursor is None:
                break

        last_sync_at = datetime.now(timezone.utc)
        update_account_status(
            connector_id, user_id,
            status="connected",
            last_sync_at=last_sync_at,
        )
        imported_count = count_imported_items(connector_id, user_id)
        _patch_run(
            connector_id, user_id,
            status="completed",
            imported_count=imported_count,
            last_sync_at=last_sync_at.isoformat(),
        )
        logger.info(
            "[connector:%s] [user:%s] import done — %d items this run (%d total)",
            connector_id, user_id[:8], total_imported, imported_count,
        )
    except Exception as exc:
        logger.error(
            "[connector:%s] [user:%s] import run failed: %s",
            connector_id, user_id[:8], exc, exc_info=True,
        )
        update_account_status(connector_id, user_id, status="error")
        _patch_run(connector_id, user_id, status="failed", error=str(exc))


def _worker(connector_id: str, user_id: str) -> None:
    try:
        _run_import(connector_id, user_id)
    except Exception as exc:
        logger.error(
            "[connector:%s] [user:%s] worker crashed: %s",
            connector_id, user_id[:8], exc, exc_info=True,
        )
        _patch_run(connector_id, user_id, status="failed", error=str(exc))


def _start_import(connector_id: str, user_id: str) -> None:
    """Spin up a background thread for the import run (idempotent if already running)."""
    key = _run_key(connector_id, user_id)
    with _LOCK:
        existing = _RUNS.get(key, {})
        if existing.get("status") == "running":
            return  # already running; caller should 409 if they want
        _RUNS[key] = {
            "status": "running",
            "imported_count": 0,
            "last_sync_at": None,
            "error": None,
        }
    threading.Thread(
        target=_worker,
        args=(connector_id, user_id),
        daemon=True,
    ).start()


# ── Public API — import control ───────────────────────────────────────────────

def start_sync(connector_id: str, user_id: str) -> None:
    """Start (or restart) a sync. Raises RuntimeError if one is already running."""
    key = _run_key(connector_id, user_id)
    with _LOCK:
        if _RUNS.get(key, {}).get("status") == "running":
            raise RuntimeError("import already running")
    account = get_account(connector_id, user_id)
    if account is None:
        raise ValueError("not connected")
    _start_import(connector_id, user_id)


def get_import_status(connector_id: str, user_id: str) -> dict:
    """Return current import status for the dashboard."""
    key = _run_key(connector_id, user_id)
    with _LOCK:
        state = dict(_RUNS[key]) if key in _RUNS else None

    account = get_account(connector_id, user_id)
    imported_count = count_imported_items(connector_id, user_id)

    if state is None:
        return {
            "running": False,
            "status": account["status"] if account else None,
            "imported_count": imported_count,
            "last_sync_at": (
                account["last_sync_at"].isoformat()
                if account and account["last_sync_at"] else None
            ),
        }
    return {
        "running": state["status"] == "running",
        "status": state["status"],
        "imported_count": state.get("imported_count", imported_count),
        "last_sync_at": state.get("last_sync_at") or (
            account["last_sync_at"].isoformat()
            if account and account["last_sync_at"] else None
        ),
    }


def disconnect(connector_id: str, user_id: str) -> None:
    """Remove the connector account. Best-effort token revoke is skipped
    (providers differ; the access token expires naturally)."""
    delete_account(connector_id, user_id)
    # Clear any in-memory run state.
    key = _run_key(connector_id, user_id)
    with _LOCK:
        _RUNS.pop(key, None)
    logger.info("[connector:%s] [user:%s] disconnected", connector_id, user_id[:8])
