-- 0018: Coupons / access tokens for testers & early adopters
--
-- Mirrors billing/coupons.py::init_coupons_db (the repo's bootstrap-at-startup
-- convention). A coupon grants a plan tier for a fixed number of days without
-- Stripe — used during the test phase so testers get Max access for free.
--
-- The grant is applied by writing users.plan + users.plan_expires_at; the coupon
-- path in billing/plans.py::effective_plan honours that expiry independently of
-- the Stripe subscription_status field.

CREATE TABLE IF NOT EXISTS coupons (
    code             VARCHAR(64) PRIMARY KEY,           -- stored upper-cased
    plan             VARCHAR(32)  NOT NULL DEFAULT 'max',
    duration_days    INT          NOT NULL DEFAULT 30,
    max_redemptions  INT,                               -- NULL = unlimited
    redeemed_count   INT          NOT NULL DEFAULT 0,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    expires_at       TIMESTAMPTZ,                        -- coupon validity window (NULL = forever)
    note             TEXT,
    created_at       TIMESTAMPTZ  DEFAULT now()
);

-- One redemption per (coupon, user); also the audit trail of who used what.
CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coupon_code   VARCHAR(64) NOT NULL REFERENCES coupons(code) ON DELETE CASCADE,
    user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granted_plan  VARCHAR(32) NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    redeemed_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (coupon_code, user_id)
);

CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user ON coupon_redemptions(user_id);
