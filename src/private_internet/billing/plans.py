"""Subscription tiers and per-feature gating — the single source of truth.

Three tiers, ranked free < pro < max:

    free  — Health, Jobs, Finances/Banking, Memory/Brain, PULSE text-only posts
    pro   — ARIA (music), SIGNAL (video), PULSE images + short video clips
    max   — STORIES

Anything NOT listed in ``FEATURE_MIN_PLAN`` is free. The frontend mirrors these
two maps (served via /api/billing/status) so gating stays in one place.

Gating is INERT while billing is disabled: ``effective_plan`` returns "max" when
``billing_enabled`` is False, so the current deployment is unaffected until
Stripe prices + the flag are configured.
"""

from datetime import datetime, timezone

from private_internet.config import get_settings

# Tier ordering. Higher rank includes everything below it.
PLAN_RANK = {"free": 0, "pro": 1, "max": 2}

# feature key -> minimum plan required. Features absent here are free for all.
FEATURE_MIN_PLAN = {
    "aria": "pro",          # AI music (ElevenLabs/Suno)
    "signal": "pro",        # AI video channel
    "pulse_media": "pro",   # PULSE images + short video clips (text stays free)
    "stories": "max",       # AI short-form films/series (lots of video)
}

# Stripe subscription statuses that grant the user's paid plan.
ENTITLED_STATUSES = {"active", "trialing"}


def plan_rank(plan: str | None) -> int:
    return PLAN_RANK.get(plan or "free", 0)


def plan_to_price(plan: str) -> str | None:
    """Stripe price id for a paid plan (None for free / unconfigured)."""
    settings = get_settings()
    if plan == "pro":
        # stripe_price_id is the legacy single-tier price; treat it as the pro
        # price when stripe_price_pro is unset so old configs keep working.
        return settings.stripe_price_pro or settings.stripe_price_id or None
    if plan == "max":
        return settings.stripe_price_max or None
    return None


def price_to_plan(price_id: str | None) -> str | None:
    """Map a Stripe price id back to its plan tier (None if unrecognised)."""
    if not price_id:
        return None
    settings = get_settings()
    if price_id == settings.stripe_price_max and settings.stripe_price_max:
        return "max"
    if price_id in (settings.stripe_price_pro, settings.stripe_price_id) and price_id:
        return "pro"
    return None


def _coupon_grant_active(user: dict) -> bool:
    """Whether the user holds an unexpired comp grant (coupon redemption).

    ``plan_expires_at`` is set only by coupon grants (Stripe uses
    ``subscription_current_period_end`` instead and never writes this column), so
    a future value here means an active comp. Tolerates both ISO strings (the
    serialized user dict) and datetime objects.
    """
    raw = user.get("plan_expires_at")
    if not raw:
        return False
    expires = raw
    if isinstance(raw, str):
        try:
            expires = datetime.fromisoformat(raw)
        except ValueError:
            return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def effective_plan(user: dict) -> str:
    """The plan a user effectively has right now.

    - billing disabled        -> "max" (everything open; current prod behaviour)
    - admin                   -> "max"
    - active coupon grant      -> users.plan (comped via a redeemed code)
    - subscription not active  -> "free" (even if users.plan says otherwise)
    - else                    -> users.plan (default "free")
    """
    settings = get_settings()
    if not settings.billing_enabled:
        return "max"
    if user.get("is_admin"):
        return "max"
    plan = user.get("plan") or "free"
    if plan not in PLAN_RANK:
        plan = "free"
    # A live coupon grant entitles the user regardless of any Stripe status.
    if _coupon_grant_active(user):
        return plan
    status = user.get("subscription_status") or "inactive"
    if status not in ENTITLED_STATUSES:
        return "free"
    return plan


def has_feature(user: dict, feature: str) -> bool:
    """Whether ``user`` may use ``feature`` given their effective plan."""
    need = FEATURE_MIN_PLAN.get(feature)
    if need is None:
        return True  # free feature
    return plan_rank(effective_plan(user)) >= plan_rank(need)


def feature_enabled_for_user(user_id: str, feature: str) -> bool:
    """has_feature() for a background job that only has the user id.

    Used by the per-user content generators (cron fans them over ALL users via
    run_for_all_users, so each generator must self-gate). Lazy import keeps this
    module free of a users.service dependency at import time.
    """
    from private_internet.users.service import get_user_by_id

    user = get_user_by_id(user_id) or {}
    return has_feature(user, feature)
