"""Minimal Stripe REST client over httpx — no SDK dependency.

Only the few calls the membership flow needs: create a customer, a Checkout
Session (subscription mode), a Billing Portal session, and verify webhook
signatures. Stripe's API is form-encoded; responses are JSON.

The secret key is read from settings (env), never hard-coded.
"""

import hashlib
import hmac
import logging
import time

import httpx

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.stripe.com/v1"
_TIMEOUT = 20.0


class StripeError(RuntimeError):
    pass


def _auth() -> tuple[str, str]:
    key = get_settings().stripe_secret_key
    if not key:
        raise StripeError("STRIPE_SECRET_KEY is not configured")
    return (key, "")  # HTTP basic: key as username, empty password


def _post(path: str, data: dict) -> dict:
    try:
        resp = httpx.post(f"{_API_BASE}{path}", data=data, auth=_auth(), timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        raise StripeError(f"Stripe request failed: {e}") from e
    body = resp.json()
    if resp.status_code >= 400:
        msg = (body.get("error") or {}).get("message", f"HTTP {resp.status_code}")
        raise StripeError(msg)
    return body


def create_customer(email: str, user_id: str) -> str:
    """Create a Stripe customer and return its id."""
    body = _post("/customers", {"email": email, "metadata[user_id]": user_id})
    return body["id"]


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    client_reference_id: str,
    trial_days: int = 0,
) -> str:
    """Create a subscription Checkout Session; return the hosted URL."""
    data = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": client_reference_id,
        "allow_promotion_codes": "true",
    }
    if trial_days > 0:
        data["subscription_data[trial_period_days]"] = str(trial_days)
    body = _post("/checkout/sessions", data)
    return body["url"]


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Create a Billing Portal session (manage/cancel); return the URL."""
    body = _post("/billing_portal/sessions", {"customer": customer_id, "return_url": return_url})
    return body["url"]


def verify_webhook_signature(payload: bytes, sig_header: str, secret: str, tolerance: int = 300) -> bool:
    """Verify a Stripe webhook signature (the `Stripe-Signature` header).

    Header format: ``t=<ts>,v1=<sig>[,v1=<sig>...]``. We recompute
    HMAC-SHA256 over ``"<ts>.<payload>"`` with the endpoint signing secret.
    """
    if not secret or not sig_header:
        return False
    ts: str | None = None
    sigs: list[str] = []
    for part in sig_header.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == "t":
            ts = v
        elif k == "v1":
            sigs.append(v)
    if ts is None or not sigs:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
    except ValueError:
        return False
    signed = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)
