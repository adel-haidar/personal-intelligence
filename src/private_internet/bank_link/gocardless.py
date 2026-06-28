"""GoCardless Bank Account Data (ex-Nordigen) REST client.

Docs: https://developer.gocardless.com/bank-account-data/

Auth model: ONE operator-level (secret_id, secret_key) pair, exchanged for a
short-lived access token. We never see the user's bank credentials — the user
authenticates at their own bank during the consent redirect, and GoCardless
returns account ids we can read balances/transactions from.

Rate limits: GoCardless caps balances/transactions/details at 4 requests per
account per day. The daily poll makes at most 3 per account, so a manual
"Sync now" plus the nightly run stays under the cap.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds

# Module-level access-token cache. GoCardless access tokens live ~24h; we refresh
# a few minutes early. Guarded by a lock so concurrent requests don't stampede.
_token_lock = threading.Lock()
_token_cache: dict[str, Any] = {"access": None, "expires_at": 0.0}


class GoCardlessError(RuntimeError):
    """Raised when the GoCardless API returns a non-2xx response."""


def is_configured() -> bool:
    """True when operator GoCardless credentials are present."""
    s = get_settings()
    return bool(s.gocardless_secret_id and s.gocardless_secret_key)


def _base_url() -> str:
    return get_settings().gocardless_base_url.rstrip("/")


def _request(method: str, path: str, *, token: str | None = None, json: dict | None = None) -> Any:
    url = f"{_base_url()}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.request(method, url, headers=headers, json=json, timeout=_TIMEOUT)
    if resp.is_error:
        # Avoid leaking secrets; GoCardless error bodies are safe to log.
        raise GoCardlessError(
            f"GoCardless {method} {path} → {resp.status_code}: {resp.text[:500]}"
        )
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def _access_token() -> str:
    """Return a cached operator access token, refreshing when near expiry."""
    now = time.time()
    with _token_lock:
        if _token_cache["access"] and _token_cache["expires_at"] - 120 > now:
            return _token_cache["access"]
        s = get_settings()
        data = _request(
            "POST",
            "/api/v2/token/new/",
            json={"secret_id": s.gocardless_secret_id, "secret_key": s.gocardless_secret_key},
        )
        access = data["access"]
        # access_expires is seconds-to-live (typically 86400).
        ttl = float(data.get("access_expires", 86400))
        _token_cache["access"] = access
        _token_cache["expires_at"] = now + ttl
        return access


# ── Public API ──────────────────────────────────────────────────────────────


def list_institutions(country: str = "de") -> list[dict]:
    """Return the available banks for a country (id, name, bic, logo, …)."""
    token = _access_token()
    data = _request("GET", f"/api/v2/institutions/?country={country}", token=token)
    return data or []


def create_requisition(institution_id: str, *, redirect: str, reference: str) -> dict:
    """Create an end-user agreement + requisition and return {id, link}.

    The agreement asks for 90 days of history and 180 days of access; the
    requisition's `link` is the consent URL we send the user to.
    """
    token = _access_token()
    agreement = _request(
        "POST",
        "/api/v2/agreements/enduser/",
        token=token,
        json={
            "institution_id": institution_id,
            "max_historical_days": 90,
            "access_valid_for_days": 180,
            "access_scope": ["balances", "details", "transactions"],
        },
    )
    requisition = _request(
        "POST",
        "/api/v2/requisitions/",
        token=token,
        json={
            "institution_id": institution_id,
            "redirect": redirect,
            "reference": reference,
            "agreement": agreement["id"],
            "user_language": "DE",
        },
    )
    return requisition


def get_requisition(requisition_id: str) -> dict:
    """Return a requisition (status + granted account ids)."""
    token = _access_token()
    return _request("GET", f"/api/v2/requisitions/{requisition_id}/", token=token)


def delete_requisition(requisition_id: str) -> None:
    """Revoke a requisition (best-effort; ignores 404)."""
    token = _access_token()
    try:
        _request("DELETE", f"/api/v2/requisitions/{requisition_id}/", token=token)
    except GoCardlessError as exc:
        logger.warning("delete_requisition %s failed (ignored): %s", requisition_id, exc)


def get_balances(account_id: str) -> list[dict]:
    """Return the balances array for an account."""
    token = _access_token()
    data = _request("GET", f"/api/v2/accounts/{account_id}/balances/", token=token)
    return (data or {}).get("balances", [])


def get_transactions(account_id: str) -> list[dict]:
    """Return the booked transactions for an account (default ~90-day window)."""
    token = _access_token()
    data = _request("GET", f"/api/v2/accounts/{account_id}/transactions/", token=token)
    return (data or {}).get("transactions", {}).get("booked", [])


def get_details(account_id: str) -> dict:
    """Return account details (IBAN, name, currency, …)."""
    token = _access_token()
    data = _request("GET", f"/api/v2/accounts/{account_id}/details/", token=token)
    return (data or {}).get("account", {})
