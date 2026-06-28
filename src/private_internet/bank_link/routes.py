"""Bank-link REST API.

Frozen contract (do not rename or restructure these endpoints):
  GET    /api/bank/institutions?country=de   → { institutions: [...] }   (filtered to Sparkasse/Volksbank)
  GET    /api/bank/authorize?institution_id=  → { authorize_url }
  GET    /api/bank/callback?ref=              → 302 redirect (no auth dependency — bank calls it)
  POST   /api/bank/sync                       → sync summary
  GET    /api/bank/status                     → status dict
  DELETE /api/bank                            → { disconnected: true }
  POST   /api/bank/poll-all                   → nightly fan-out (INTERNAL_SECRET header)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from private_internet.bank_link import gocardless, service
from private_internet.config import get_settings
from private_internet.content.router import _require_internal_secret
from private_internet.core.request_context import RequestContext, get_request_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bank")

# v1 scope: surface only Sparkassen and Volksbanks. These substrings match the
# GoCardless institution `name`/`id` for the German cooperative + savings banks.
_V1_BANK_MATCH = ("sparkasse", "volksbank", "raiffeisen", "vr-bank", "vr bank", "vereinigte volksbank")


def _frontend_base() -> str:
    return get_settings().base_url


def _require_configured() -> None:
    if not gocardless.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Bank connections are not configured on this instance (missing GoCardless keys).",
        )


# ── Institution picker ────────────────────────────────────────────────────────

@router.get("/institutions")
async def list_institutions(
    country: str = "de",
    ctx: RequestContext = Depends(get_request_context),
):
    """Return the Sparkasse/Volksbank institutions available for a country."""
    _require_configured()
    try:
        all_inst = await run_in_threadpool(gocardless.list_institutions, country)
    except Exception as exc:
        logger.error("list_institutions failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach the bank directory.") from exc

    def _is_v1(inst: dict) -> bool:
        hay = f"{inst.get('name', '')} {inst.get('id', '')}".lower()
        return any(m in hay for m in _V1_BANK_MATCH)

    institutions = [
        {"id": i["id"], "name": i.get("name", i["id"]), "logo": i.get("logo"), "bic": i.get("bic")}
        for i in all_inst if _is_v1(i)
    ]
    institutions.sort(key=lambda i: i["name"])
    return {"institutions": institutions}


# ── Build consent URL ─────────────────────────────────────────────────────────

@router.get("/authorize")
async def authorize(
    institution_id: str = Query(...),
    institution_name: str = Query(""),
    ctx: RequestContext = Depends(get_request_context),
):
    """Create a requisition and return the bank consent URL to open."""
    _require_configured()
    try:
        url = await run_in_threadpool(
            service.build_authorize, institution_id, ctx.user_id,
        )
    except Exception as exc:
        logger.error("build_authorize failed for %s: %s", institution_id, exc)
        raise HTTPException(status_code=502, detail="Could not start bank connection.") from exc
    return {"authorize_url": url}


# ── Consent callback (no auth dependency — GoCardless redirects here) ──────────

@router.get("/callback")
async def callback(ref: str = "", error: str = ""):
    """GoCardless consent callback. Redirects to /finances on success/failure."""
    base = _frontend_base()
    if error or not ref:
        logger.warning("[bank] callback error=%s ref_present=%s", error, bool(ref))
        return RedirectResponse(f"{base}/finances?bank_error=1", status_code=302)
    try:
        await run_in_threadpool(service.handle_callback, ref)
    except Exception as exc:
        logger.error("[bank] handle_callback failed: %s", exc)
        return RedirectResponse(f"{base}/finances?bank_error=1", status_code=302)
    return RedirectResponse(f"{base}/finances?bank_connected=1", status_code=302)


# ── Manual sync ───────────────────────────────────────────────────────────────

@router.post("/sync")
async def sync_now(ctx: RequestContext = Depends(get_request_context)):
    """Re-poll the connected bank now (runs inline; returns a summary)."""
    try:
        summary = await run_in_threadpool(service.sync_connection, ctx.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[bank] manual sync failed: %s", exc)
        raise HTTPException(status_code=502, detail="Bank sync failed. Try again later.") from exc
    return {"synced": True, **summary}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def status(ctx: RequestContext = Depends(get_request_context)):
    """Return the user's bank-connection status."""
    return service.get_status(ctx.user_id)


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.delete("")
async def disconnect(ctx: RequestContext = Depends(get_request_context)):
    """Revoke consent and remove the connection (brain memories are kept)."""
    await run_in_threadpool(service.disconnect, ctx.user_id)
    return {"disconnected": True}


# ── Nightly fan-out (internal: systemd timer) ─────────────────────────────────

@router.post("/poll-all")
async def poll_all(_: None = Depends(_require_internal_secret)):
    """Poll every connected user's bank. Called by the bank-poll systemd timer."""
    return await run_in_threadpool(service.poll_all_users)
