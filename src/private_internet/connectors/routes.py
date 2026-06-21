"""Connectors REST API.

Frozen contract (do not rename or restructure these endpoints):
  GET    /api/connectors                     → list all tiles
  GET    /api/connectors/{id}/authorize      → { authorize_url }
  GET    /api/connectors/{id}/callback       → 302 redirect (no auth dependency)
  POST   /api/connectors/{id}/sync           → { started: true }
  GET    /api/connectors/{id}/status         → status dict
  DELETE /api/connectors/{id}                → { disconnected: true }
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from private_internet.config import get_settings
from private_internet.connectors.db import get_account
from private_internet.connectors.registry import COMING_SOON, get_connector, list_connector_meta
from private_internet.connectors.service import (
    build_authorize,
    disconnect,
    get_import_status,
    handle_callback,
    start_sync,
)
from private_internet.core.request_context import RequestContext, get_request_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors")

_COMING_SOON_IDS = {c["id"] for c in COMING_SOON}


def _frontend_base() -> str:
    """Return the base URL to redirect to after OAuth callbacks."""
    return get_settings().base_url


# ── List all connectors ────────────────────────────────────────────────────────

@router.get("")
async def list_connectors(ctx: RequestContext = Depends(get_request_context)):
    """Return tile metadata for every connector (real + coming soon)."""
    tiles = list_connector_meta(ctx.user_id)
    return {"connectors": tiles}


# ── Build authorize URL ────────────────────────────────────────────────────────

@router.get("/{connector_id}/authorize")
async def get_authorize_url(
    connector_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return the OAuth authorize URL for the frontend to open."""
    if connector_id in _COMING_SOON_IDS:
        raise HTTPException(status_code=400, detail=f"{connector_id} is not yet available")
    connector = get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_id}")
    if not connector.is_configured():
        raise HTTPException(
            status_code=400,
            detail=f"{connector_id} is not configured on this instance (missing client id/secret)",
        )
    try:
        url = build_authorize(connector_id, ctx.user_id)
    except Exception as exc:
        logger.error("build_authorize failed for %s: %s", connector_id, exc)
        raise HTTPException(status_code=500, detail="Failed to build authorize URL") from exc
    return {"authorize_url": url}


# ── OAuth callback (no auth dependency — provider calls this) ─────────────────

@router.get("/{connector_id}/callback")
async def oauth_callback(
    connector_id: str,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """OAuth authorization-code callback. Exchanges code, stores creds, starts import.
    Redirects to /memory?connected={id} on success or /memory?connect_error={id} on failure.
    """
    base = _frontend_base()
    success_url = f"{base}/memory?connected={connector_id}"
    error_url = f"{base}/memory?connect_error={connector_id}"

    if error or not code or not state:
        logger.warning(
            "[connector:%s] callback error: error=%s code_present=%s state_present=%s",
            connector_id, error, bool(code), bool(state),
        )
        return RedirectResponse(error_url, status_code=302)

    connector = get_connector(connector_id)
    if connector is None:
        logger.error("[connector:%s] callback for unknown connector", connector_id)
        return RedirectResponse(error_url, status_code=302)

    try:
        handle_callback(connector_id, code, state)
    except Exception as exc:
        logger.error("[connector:%s] handle_callback failed: %s", connector_id, exc)
        return RedirectResponse(error_url, status_code=302)

    return RedirectResponse(success_url, status_code=302)


# ── Manual re-sync ─────────────────────────────────────────────────────────────

@router.post("/{connector_id}/sync")
async def sync_connector(
    connector_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Re-run the import for an already-connected connector."""
    if connector_id in _COMING_SOON_IDS:
        raise HTTPException(status_code=400, detail=f"{connector_id} is not yet available")
    connector = get_connector(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_id}")
    account = get_account(connector_id, ctx.user_id)
    if account is None:
        raise HTTPException(status_code=400, detail=f"Not connected to {connector_id}")
    try:
        start_sync(connector_id, ctx.user_id)
    except RuntimeError as exc:
        # Already running.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"started": True}


# ── Import status ──────────────────────────────────────────────────────────────

@router.get("/{connector_id}/status")
async def connector_status(
    connector_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Return the current import status for a connector."""
    if connector_id in _COMING_SOON_IDS:
        raise HTTPException(status_code=400, detail=f"{connector_id} is not yet available")
    if get_connector(connector_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_id}")
    account = get_account(connector_id, ctx.user_id)
    status = get_import_status(connector_id, ctx.user_id)
    return {
        "connected": account is not None,
        **status,
    }


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.delete("/{connector_id}")
async def disconnect_connector(
    connector_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    """Remove a connector connection for the authenticated user."""
    if connector_id in _COMING_SOON_IDS:
        raise HTTPException(status_code=400, detail=f"{connector_id} is not yet available")
    if get_connector(connector_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {connector_id}")
    disconnect(connector_id, ctx.user_id)
    return {"disconnected": True}
