"""Coupons / access tokens — comp the paid plan without Stripe.

Testers and early adopters redeem a code to get a paid tier (Max by default) for
a fixed number of days. The grant is written to ``users.plan`` +
``users.plan_expires_at``; ``billing/plans.py::effective_plan`` honours that
expiry independently of the Stripe ``subscription_status`` field, so a coupon
user never touches Stripe and the Billing Portal link stays hidden for them.

Schema lives in migrations/0018_coupons.sql; ``init_coupons_db`` mirrors it for
the bootstrap-at-startup convention.
"""

import logging
from datetime import datetime, timedelta, timezone

from psycopg2.extras import RealDictCursor

from private_internet.billing.plans import PLAN_RANK
from private_internet.config import get_settings
from private_internet.database import _connect
from private_internet.users.service import grant_plan

logger = logging.getLogger(__name__)


class CouponError(Exception):
    """Redemption refused — the message is safe to show the user."""


def _normalize(code: str) -> str:
    return (code or "").strip().upper()


def init_coupons_db() -> None:
    """Create the coupons tables (mirrors migrations/0018_coupons.sql)."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                code             VARCHAR(64) PRIMARY KEY,
                plan             VARCHAR(32)  NOT NULL DEFAULT 'max',
                duration_days    INT          NOT NULL DEFAULT 30,
                max_redemptions  INT,
                redeemed_count   INT          NOT NULL DEFAULT 0,
                is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
                expires_at       TIMESTAMPTZ,
                note             TEXT,
                created_at       TIMESTAMPTZ  DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS coupon_redemptions (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                coupon_code   VARCHAR(64) NOT NULL REFERENCES coupons(code) ON DELETE CASCADE,
                user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                granted_plan  VARCHAR(32) NOT NULL,
                expires_at    TIMESTAMPTZ NOT NULL,
                redeemed_at   TIMESTAMPTZ DEFAULT now(),
                UNIQUE (coupon_code, user_id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user "
            "ON coupon_redemptions(user_id)"
        )
        conn.commit()
        logger.info("Coupons schema ready")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def seed_tester_coupons() -> None:
    """Seed multi-use Max coupons from ``TESTER_COUPONS`` (comma-separated).

    Idempotent: re-asserts the codes' grant terms without resetting their
    redeemed_count, so a redeploy never wipes the audit trail.
    """
    settings = get_settings()
    codes = [_normalize(c) for c in (settings.tester_coupons or "").split(",")]
    codes = [c for c in codes if c]
    if not codes:
        return
    conn = _connect()
    cur = conn.cursor()
    try:
        for code in codes:
            cur.execute(
                """INSERT INTO coupons (code, plan, duration_days, max_redemptions,
                                        is_active, note)
                   VALUES (%s, 'max', 30, NULL, TRUE, 'Seeded from TESTER_COUPONS')
                   ON CONFLICT (code) DO UPDATE SET
                     plan = EXCLUDED.plan,
                     duration_days = EXCLUDED.duration_days,
                     max_redemptions = EXCLUDED.max_redemptions,
                     is_active = TRUE""",
                (code,),
            )
        conn.commit()
        logger.info(f"Seeded {len(codes)} tester coupon(s)")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def redeem_coupon(user_id: str, code: str) -> dict:
    """Redeem ``code`` for ``user_id``; grant the coupon's plan for its window.

    Returns ``{"plan", "plan_expires_at"}`` on success. Raises ``CouponError``
    with a user-safe message on any failure (unknown/inactive/expired/used-up
    code, or already redeemed by this user).
    """
    code = _normalize(code)
    if not code:
        raise CouponError("Enter a code.")

    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Lock the coupon row so concurrent redemptions can't oversell a limit.
        cur.execute("SELECT * FROM coupons WHERE code = %s FOR UPDATE", (code,))
        coupon = cur.fetchone()
        if coupon is None or not coupon["is_active"]:
            raise CouponError("That code isn't valid.")

        now = datetime.now(timezone.utc)
        if coupon["expires_at"] and coupon["expires_at"] < now:
            raise CouponError("That code has expired.")
        if (
            coupon["max_redemptions"] is not None
            and coupon["redeemed_count"] >= coupon["max_redemptions"]
        ):
            raise CouponError("That code has already been fully redeemed.")

        # Already redeemed by this user? (the UNIQUE constraint also guards this)
        cur.execute(
            "SELECT 1 FROM coupon_redemptions WHERE coupon_code = %s AND user_id = %s",
            (code, user_id),
        )
        if cur.fetchone():
            raise CouponError("You've already redeemed this code.")

        plan = coupon["plan"] if coupon["plan"] in PLAN_RANK else "max"
        expires_at = now + timedelta(days=int(coupon["duration_days"]))

        cur.execute(
            """INSERT INTO coupon_redemptions
                   (coupon_code, user_id, granted_plan, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (code, user_id, plan, expires_at),
        )
        cur.execute(
            "UPDATE coupons SET redeemed_count = redeemed_count + 1 WHERE code = %s",
            (code,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Apply the grant on a fresh connection (its own commit).
    grant_plan(user_id, plan=plan, expires_at=expires_at)
    logger.info(f"[user:{user_id[:8]}] redeemed coupon {code} -> {plan} until {expires_at.date()}")
    return {"plan": plan, "plan_expires_at": expires_at.isoformat()}
