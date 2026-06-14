"""Subscription entitlement + Stripe webhook event handling."""

import logging
from datetime import datetime, timezone

from private_internet.billing import stripe_client
from private_internet.config import get_settings
from private_internet.users.service import (
    get_user_by_stripe_customer_id,
    set_stripe_customer_id,
    set_subscription,
)

logger = logging.getLogger(__name__)

# Stripe subscription statuses that grant access.
ENTITLED_STATUSES = {"active", "trialing"}


def is_entitled(user: dict) -> bool:
    """Whether a user may use the gated product.

    When billing is disabled (default), everyone is entitled — so the current
    deployment is unaffected until keys + the flag are set. Admins always pass.
    """
    settings = get_settings()
    if not settings.billing_enabled:
        return True
    if user.get("is_admin"):
        return True
    return (user.get("subscription_status") or "inactive") in ENTITLED_STATUSES


def ensure_customer(user: dict) -> str:
    """Return the user's Stripe customer id, creating + persisting one if needed."""
    existing = user.get("stripe_customer_id")
    if existing:
        return existing
    customer_id = stripe_client.create_customer(user["email"], str(user["id"]))
    set_stripe_customer_id(str(user["id"]), customer_id)
    return customer_id


def _ts_to_dt(ts) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def handle_event(event: dict) -> None:
    """Apply a verified Stripe webhook event to the user's subscription state."""
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        customer = obj.get("customer")
        subscription = obj.get("subscription")
        if user_id:
            if customer:
                set_stripe_customer_id(str(user_id), customer)
            # The authoritative status arrives via subscription.* shortly after;
            # mark active now so the user isn't bounced on the success redirect.
            set_subscription(str(user_id), status="active", stripe_subscription_id=subscription)
            logger.info(f"[user:{str(user_id)[:8]}] checkout completed")

    elif etype in ("customer.subscription.created", "customer.subscription.updated"):
        customer = obj.get("customer")
        user = get_user_by_stripe_customer_id(customer) if customer else None
        if user:
            set_subscription(
                str(user["id"]),
                status=obj.get("status", "active"),
                stripe_subscription_id=obj.get("id"),
                current_period_end=_ts_to_dt(obj.get("current_period_end")),
            )
            logger.info(f"[user:{str(user['id'])[:8]}] subscription -> {obj.get('status')}")

    elif etype == "customer.subscription.deleted":
        customer = obj.get("customer")
        user = get_user_by_stripe_customer_id(customer) if customer else None
        if user:
            set_subscription(str(user["id"]), status="canceled", stripe_subscription_id=obj.get("id"))
            logger.info(f"[user:{str(user['id'])[:8]}] subscription canceled")

    else:
        logger.debug(f"Ignoring Stripe event: {etype}")
