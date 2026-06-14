# Billing (Stripe) — setup

Membership uses **Stripe Checkout** (hosted) + a webhook. The app reads all
keys from the environment — **no keys are committed**. While `BILLING_ENABLED`
is `false` (the default) the app is **not** gated on a subscription, so existing
users and the current deployment are unaffected until you switch it on.

## Environment variables

| Var | Meaning |
|-----|---------|
| `BILLING_ENABLED` | `true` to gate the app behind an active subscription |
| `STRIPE_SECRET_KEY` | `sk_test_…` / `sk_live_…` |
| `STRIPE_PRICE_ID` | the recurring Price users subscribe to (`price_…`) |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` from the webhook endpoint (required for status to update) |
| `STRIPE_TRIAL_DAYS` | `0` = none; `>0` = card-required free trial |

Local dev: put these in `.env` (gitignored). Production: set them in the
systemd/deploy environment (per the repo's "secrets via env only" rule).

A **test Price already exists**: `price_1Ti8HX0GpcdOy5XSSOIHPeY2` (€9.00/month).
Change the amount in the Stripe Dashboard (Products) or create a new Price and
update `STRIPE_PRICE_ID`.

## Webhook

Create an endpoint pointing at `POST https://<domain>/api/billing/webhook` and
subscribe to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Copy its signing secret into `STRIPE_WEBHOOK_SECRET`. **Without this, a paid
subscription will never flip the user's status to active.**

Local testing: `stripe listen --forward-to localhost:8000/api/billing/webhook`
prints a `whsec_…` to use.

## Endpoints (Service A)

- `GET  /api/billing/status`  → `{ billing_enabled, entitled, subscription_status, … }`
- `POST /api/billing/checkout` → `{ url }` (redirect the browser to it)
- `POST /api/billing/portal`   → `{ url }` (manage/cancel; needs an existing customer)
- `POST /api/billing/webhook`  → Stripe → us, signature-verified

## How it gates

`subscription_status ∈ {active, trialing}` (or `is_admin`) ⇒ entitled. The Vue
router guard sends unentitled users to `/subscribe` when billing is enabled;
the subscribe screen calls `/checkout` and redirects to Stripe.

> Note: gating today is enforced at the API/route boundary the frontend uses.
> Server-side enforcement on the content-generation pipelines (so unentitled
> users don't incur Bedrock cost) is a follow-up.
