"""Billing endpoints: subscription status, Checkout, Billing Portal, webhook."""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from private_internet.billing import service, stripe_client
from private_internet.config import get_settings
from private_internet.core.request_context import RequestContext, get_request_context
from private_internet.users.service import get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@router.get("/status")
async def status(ctx: RequestContext = Depends(get_request_context)):
    settings = get_settings()
    user = get_user_by_id(ctx.user_id) or {}
    return {
        "billing_enabled": settings.billing_enabled,
        "subscription_status": user.get("subscription_status") or "inactive",
        "entitled": service.is_entitled(user),
        "trial_days": settings.stripe_trial_days,
        "price_configured": bool(settings.stripe_price_id),
        "current_period_end": user.get("subscription_current_period_end"),
    }


@router.post("/checkout")
async def checkout(ctx: RequestContext = Depends(get_request_context)):
    settings = get_settings()
    if not settings.billing_enabled:
        return _error(400, "Billing is not enabled on this server.")
    if not settings.stripe_price_id:
        return _error(500, "Billing is misconfigured — no price set.")
    user = get_user_by_id(ctx.user_id)
    if not user:
        return _error(404, "User not found.")
    try:
        customer_id = service.ensure_customer(user)
        url = stripe_client.create_checkout_session(
            customer_id=customer_id,
            price_id=settings.stripe_price_id,
            success_url=f"{settings.base_url}/overview?checkout=success",
            cancel_url=f"{settings.base_url}/subscribe?checkout=cancel",
            client_reference_id=str(user["id"]),
            trial_days=settings.stripe_trial_days,
        )
    except stripe_client.StripeError as e:
        logger.error(f"{ctx.log_prefix} checkout failed: {e}")
        return _error(502, "Could not start checkout. Please try again.")
    return {"url": url}


@router.post("/portal")
async def portal(ctx: RequestContext = Depends(get_request_context)):
    settings = get_settings()
    user = get_user_by_id(ctx.user_id)
    if not user or not user.get("stripe_customer_id"):
        return _error(400, "No billing account yet — subscribe first.")
    try:
        url = stripe_client.create_portal_session(
            customer_id=user["stripe_customer_id"],
            return_url=f"{settings.base_url}/settings",
        )
    except stripe_client.StripeError as e:
        logger.error(f"{ctx.log_prefix} portal failed: {e}")
        return _error(502, "Could not open the billing portal.")
    return {"url": url}


@router.post("/webhook")
async def webhook(request: Request):
    """Stripe → us. Public, but every call is signature-verified."""
    settings = get_settings()
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    if not stripe_client.verify_webhook_signature(payload, sig, settings.stripe_webhook_secret):
        return _error(400, "Invalid signature.")
    try:
        event = json.loads(payload)
    except ValueError:
        return _error(400, "Invalid payload.")
    try:
        service.handle_event(event)
    except Exception as e:  # let Stripe retry on transient DB errors
        logger.error(f"Stripe webhook handling failed: {e}", exc_info=True)
        return _error(500, "Webhook handler error.")
    return {"received": True}
