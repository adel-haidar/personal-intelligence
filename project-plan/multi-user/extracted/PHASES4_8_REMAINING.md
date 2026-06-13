# PHASE 4 — Public Landing Page + Registration Frontend
## Agent: Codex
## Depends on: Phase 1 (CDK deployed, domain live)

---

## Goal
Build the public-facing pages. No auth required. These are what a new visitor sees before creating an account.

---

## Pages to Build

### `/` — Landing Page

No sidebar. Full-width layout.

**Header (sticky):**
```
[Brain pulse logo]  Private Internet          [Sign in]  [Create account →]
```

**Hero section:**
- Headline: `"Your AI. Your server. Your rules."`
- Subheadline (1 sentence): `"A personal AI platform that runs on your own infrastructure — not in a corporation's cloud."`
- Two CTAs: `[Create free account]` (primary) + `[See how it works ↓]` (ghost)
- No hero image. No illustration. The animated brain pulse (64px) sits above the headline.

**Three-column value section:**
```
[Brain icon]              [Lock icon]             [Chart icon]
Everything learns         Your data never         The more you share,
from your memory          leaves your server      the smarter it gets
```

**Module preview section (three cards):**
- PULSE — "An AI social feed built around your life"
- SIGNAL — "AI-generated videos on topics that matter to you"
- Health + Finances — "Insights from your own wearables and documents"

Each card: icon, name, one sentence, no screenshots.

**Pricing section (three columns):**

| Free | Personal €9/mo | Pro €19/mo |
|------|----------------|------------|
| 50 memories | Unlimited memories | Unlimited everything |
| 5 posts/week | 20 posts/week | Unlimited posts |
| 2 videos/week | 7 videos/week | Unlimited videos |
| 500MB storage | 5GB storage | 20GB storage |
| [Get started free] | [Start Personal] | [Start Pro] |

**Footer:**
```
Private Internet    [GitHub]    [How it works]    [Privacy]
```

---

### `/register` — Registration Page

Centered card, max-width 440px.

Fields:
1. Display name
2. Email
3. Password (with strength indicator — 3 dots, fills red → amber → green)
4. Confirm password

Plan selection (if arriving from pricing page, pre-select that plan):
```
○ Free — start without a card
● Personal — €9/month (Stripe checkout after registration)
○ Pro — €19/month
```

Submit button: `Create my account →`

Below form: `"Already have an account? Sign in"`

After submit: show `"Check your inbox — we sent a verification link to {email}"` on the same page. Replace the form, do not redirect.

---

### `/login` — Login Page

Centered card, max-width 440px.

Fields: Email, Password
Button: `Sign in →`
Links: `Forgot password?` / `Create account`

Error states (shown as a single line below the button):
- `"No account found with this email address"`
- `"Incorrect password"`
- `"Please verify your email before signing in. Resend verification →"`

---

### `/forgot-password` and `/reset-password?token=...`

Standard password reset pages. Clean, minimal. No special design requirements.

---

### `/about` — How It Works

Public page. No auth. Explains the product in plain language.
Content already specified in PRODUCTIZE_PROMPT.md.

---

## Completion Criteria
- [ ] Landing page loads without auth
- [ ] Registration form validates all fields client-side before submit
- [ ] Password strength indicator updates in real time
- [ ] Plan pre-selection works from pricing links
- [ ] Post-registration shows inbox message (no redirect)
- [ ] Login shows specific error messages
- [ ] All pages work in dark and light mode
- [ ] Mobile-responsive (380px minimum)

---
---

# PHASE 5 — Transactional Email System (SES)
## Agent: Claude Code
## Depends on: Phase 1 (SES configured in CDK)

---

## Goal
All transactional emails sent via Amazon SES. HTML templates stored in code. No third-party email service.

---

## Task 1 — SES Setup (one-time)

In AWS Console (or CDK):
1. Verify domain `private.internet` in SES (add DNS records via Route 53)
2. Request production access (move out of SES sandbox) — submit via console
3. Set up DKIM and DMARC records in Route 53
4. Create SES configuration set named `private-internet-transactional`

From address: `hello@private.internet`
Reply-to: `support@private.internet`

---

## Task 2 — Email Service

Create: `backend/app/emails/ses_service.py`

```python
import boto3
from jinja2 import Environment, FileSystemLoader

class EmailService:
    def __init__(self):
        self.ses = boto3.client('ses', region_name='eu-central-1')
        self.jinja = Environment(loader=FileSystemLoader('app/emails/templates'))
        self.from_address = 'Private Internet <hello@private.internet>'

    def send(self, to: str, subject: str, template: str, context: dict) -> bool:
        html = self.jinja.get_template(f'{template}.html').render(**context)
        text = self.jinja.get_template(f'{template}.txt').render(**context)
        try:
            self.ses.send_email(
                Source=self.from_address,
                Destination={'ToAddresses': [to]},
                Message={
                    'Subject': {'Data': subject},
                    'Body': {
                        'Html': {'Data': html},
                        'Text': {'Data': text},
                    }
                },
                ConfigurationSetName='private-internet-transactional',
            )
            return True
        except Exception as e:
            log.error(f"SES send failed: {e}")
            return False
```

---

## Task 3 — Email Templates

Create: `backend/app/emails/templates/`

### `verification.html` / `verification.txt`
Subject: `"Verify your Private Internet account"`

```
Your account is ready.

One step left — click the link below to verify your email address:

[Verify my email →]  (button, links to /api/auth/verify-email?token={token})

This link expires in 24 hours.
If you didn't create an account, ignore this email.
```

### `welcome.html` / `welcome.txt`
Subject: `"Welcome to Private Internet, {name}"`
Sent after email verification.

```
Welcome, {name}.

Your private brain is ready. Here's what to do first:

→ Write your introduction — the more you share, the smarter everything gets.
→ Connect a health device to start tracking your data.
→ Upload a bank statement to start your financial analysis.

Your first posts and videos are already being prepared.

[Open Private Internet →]
```

### `password_reset.html` / `password_reset.txt`
Subject: `"Reset your Private Internet password"`

```
Someone requested a password reset for this account.

[Reset my password →]  (links to /reset-password?token={token})

This link expires in 1 hour.
If you didn't request this, no action is needed.
```

### `weekly_digest.html` / `weekly_digest.txt`  ← future, placeholder only
Subject: `"Your Private Internet week — {date}"`

---

## Completion Criteria
- [ ] SES domain verified, out of sandbox
- [ ] Verification email received in real inbox (not spam)
- [ ] Welcome email sent after verification
- [ ] Password reset email works end-to-end
- [ ] HTML emails render correctly in Gmail, Apple Mail, Outlook
- [ ] Plain text fallback is readable

---
---

# PHASE 6 — Billing & Plans (Stripe)
## Agent: Claude Code
## Depends on: Phase 2 (user records + auth), Phase 5 (emails)

---

## Goal
Integrate Stripe for subscription billing. Free tier works without a card. Paid tiers go through Stripe Checkout. Usage limits enforced at the application layer.

---

## Task 1 — Stripe Products Setup (one-time in Stripe Dashboard)

Create two products:
- **Personal** — €9/month recurring, `price_personal_monthly`
- **Pro** — €19/month recurring, `price_pro_monthly`

Save the price IDs to Secrets Manager.

---

## Task 2 — Checkout Endpoint

```python
POST /api/billing/checkout
Body: { "plan": "personal" | "pro" }
Auth: required

# Creates a Stripe Checkout Session and returns the URL.
# User is redirected to Stripe, completes payment, redirected back to /dashboard?upgraded=true
```

```python
async def create_checkout(body, current_user: User):
    stripe.api_key = STRIPE_SECRET

    # Create or retrieve Stripe customer
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            name=current_user.display_name,
            metadata={"user_id": str(current_user.id)},
        )
        current_user.stripe_customer_id = customer.id
        db.commit()

    price_id = PRICE_IDS[body.plan]
    session = stripe.checkout.Session.create(
        customer=current_user.stripe_customer_id,
        mode='subscription',
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"https://private.internet/dashboard?upgraded=true",
        cancel_url=f"https://private.internet/settings/billing",
        metadata={"user_id": str(current_user.id), "plan": body.plan},
    )
    return {"checkout_url": session.url}
```

---

## Task 3 — Stripe Webhook Handler

```python
POST /api/billing/webhook
# No auth — verified via Stripe signature

async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get('stripe-signature')
    event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)

    if event.type == 'checkout.session.completed':
        session = event.data.object
        user_id = session.metadata.get('user_id')
        plan = session.metadata.get('plan')
        # Update user.plan, user.stripe_subscription_id, user.plan_expires_at = None (ongoing)

    elif event.type == 'customer.subscription.deleted':
        # Downgrade user back to free plan
        # Set user.plan = 'free', user.plan_expires_at = now()

    elif event.type == 'invoice.payment_failed':
        # Send payment failed email
        # Grace period: keep paid features for 3 days, then downgrade

    return {"status": "ok"}
```

---

## Task 4 — Usage Limit Enforcement

Create: `backend/app/users/limits.py`

```python
class PlanLimits:
    def check_memory_limit(self, user: User, db: Session) -> None:
        limits = get_plan_limits(user.plan)
        if limits.max_memories is None:
            return  # unlimited
        count = db.query(func.count(Memory.id)).filter(Memory.user_id == user.id).scalar()
        if count >= limits.max_memories:
            raise HTTPException(403, {
                "error": "memory_limit_reached",
                "message": f"Free plan allows {limits.max_memories} memories. Upgrade to add more.",
                "upgrade_url": "/settings/billing"
            })

    def check_storage_limit(self, user: User, used_mb: float) -> None:
        limits = get_plan_limits(user.plan)
        if used_mb >= limits.max_storage_mb:
            raise HTTPException(403, {
                "error": "storage_limit_reached",
                "upgrade_url": "/settings/billing"
            })
```

Call `PlanLimits().check_memory_limit(user, db)` at the start of any endpoint that creates content.

---

## Task 5 — Billing Page (backend endpoints only — frontend in Phase 7)

```python
GET /api/billing/status
# Response:
{
  "plan": "free" | "personal" | "pro",
  "stripe_subscription_id": str | null,
  "next_billing_date": "ISO8601" | null,
  "usage": {
    "memories": { "used": 42, "limit": 50 },
    "storage_mb": { "used": 120, "limit": 500 },
    "posts_this_week": { "used": 3, "limit": 5 },
    "videos_this_week": { "used": 1, "limit": 2 },
  }
}

POST /api/billing/portal
# Creates a Stripe Customer Portal session for managing subscription
# Returns { "portal_url": str }
```

---

## Completion Criteria
- [ ] Free users can register without entering card details
- [ ] Clicking upgrade → redirects to Stripe Checkout
- [ ] After payment: user.plan updated to paid tier
- [ ] After cancellation: user downgraded to free
- [ ] Free tier limits enforced (memory count, storage, weekly posts/videos)
- [ ] Paid tiers have no limits enforced
- [ ] Stripe webhook verifies signature before processing

---
---

# PHASE 7 — Admin Dashboard
## Agent: Codex
## Depends on: Phase 2, 3 (users exist in DB)

---

## Goal
An internal admin page at `/admin` accessible only to users with `is_admin=True`. Used for monitoring, support, and operations.

---

## Pages

### `/admin` — Overview

```
PRIVATE INTERNET — ADMIN

Total users: 142          Active today: 38
Free: 98  Personal: 31  Pro: 13

MRR: €279/month           Churn this month: 2

System health:
  ECS tasks running: 2/2  ✓
  RDS connections: 14/100  ✓
  SQS queue depth: 3  ✓
  Content jobs today: 47  ✓
```

### `/admin/users` — User List

Table: email, display_name, plan, created_at, last_active_at, memory_count, provisioned, actions

Actions per user: `[View]` `[Reprovision]` `[Upgrade plan]` `[Disable]`

Search by email. Filter by plan.

### `/admin/users/{id}` — User Detail

Shows: profile, plan, memory count, post count, video count, storage used, all content generated, RL scores.

Button: `[Reprovision]` → calls `POST /api/admin/users/{id}/reprovision`

### `/admin/content` — Content Overview

Stats across all users: posts generated today/week/month, videos generated, average creator scores, top topics.

### `/admin/costs` — Cost Tracker

Estimated cost breakdown:
- Bedrock calls this month (from CloudWatch metrics)
- Polly characters synthesized (from CloudWatch)
- S3 storage used (total + per-user top 10)
- Estimated monthly bill

---

## Completion Criteria
- [ ] `/admin` only accessible to `is_admin=True` users
- [ ] User list paginated and searchable
- [ ] Reprovision button works
- [ ] All stats are real (not hardcoded)
- [ ] Mobile layout at minimum usable (admin is desktop-primary)

---
---

# PHASE 8 — Cost Controls & Usage Limits
## Agent: Claude Code
## Depends on: Phase 3, 6

---

## Goal
Prevent runaway costs from a single user or a bug in the content generation pipeline. Add hard limits, CloudWatch alarms, and an emergency kill switch.

---

## Task 1 — Per-User Generation Rate Limits

In the content job dispatcher, add a daily counter per user:

```python
def check_generation_allowed(user_id: UUID, job_type: str, db: Session) -> bool:
    """
    Enforces weekly post/video limits from plan_limits table.
    Uses a simple count query — no Redis needed at this scale.
    """
    limits = get_plan_limits_for_user(user_id, db)

    if job_type == "posts":
        if limits.max_posts_per_week is None:
            return True
        week_start = datetime.utcnow() - timedelta(days=7)
        count = db.query(func.count(ContentPost.id)).filter(
            ContentPost.user_id == user_id,
            ContentPost.created_at >= week_start
        ).scalar()
        return count < limits.max_posts_per_week

    # Same logic for videos
```

If limit reached: skip user in `run_for_all_users()` — log it, continue to next user.

---

## Task 2 — Global Emergency Kill Switch

Add to `.env` / Secrets Manager:
```
CONTENT_GENERATION_ENABLED=true
```

Check at the start of every content job:
```python
if not os.getenv("CONTENT_GENERATION_ENABLED", "true") == "true":
    log.warning("Content generation globally disabled via kill switch")
    return
```

Setting `CONTENT_GENERATION_ENABLED=false` in Secrets Manager and restarting ECS tasks stops all content generation immediately. No code deploy needed.

---

## Task 3 — CloudWatch Cost Alarms

Create CDK alarms (add to Phase 1 CDK stack):

```typescript
// Alert if Bedrock spend estimate exceeds €50 in a day
new cloudwatch.Alarm(this, 'BedrockSpendAlarm', {
  metric: new cloudwatch.Metric({
    namespace: 'AWS/Bedrock',
    metricName: 'InvocationCount',
    statistic: 'Sum',
    period: Duration.hours(24),
  }),
  threshold: 5000,    // 5000 calls/day = ~€50 at Haiku prices
  evaluationPeriods: 1,
  alarmDescription: 'Bedrock call volume unusually high',
  actionsEnabled: true,
})
// Send alarm to SNS → email to admin
```

---

## Task 4 — Storage Quota Enforcement

Run daily (add to EventBridge):
```python
async def enforce_storage_quotas(db: Session):
    """
    Check all users' S3 storage usage.
    If a user exceeds their plan limit: disable new uploads until they clear space.
    """
    s3 = boto3.client('s3')
    users = db.query(User).all()
    for user in users:
        # List all objects under user prefix and sum sizes
        total_bytes = sum_s3_prefix(s3, S3_BUCKET, f"{user.id}/")
        total_mb = total_bytes / 1024 / 1024
        limits = get_plan_limits(user.plan)
        if total_mb > limits.max_storage_mb:
            # Flag user — new uploads rejected until they delete content
            user.storage_over_limit = True
            db.commit()
            # Send warning email (via SES)
```

---

## Task 5 — Dead Letter Queue Monitor

SQS dead letter queues (created in Phase 1) receive messages that failed 3 times.

Add a CloudWatch alarm on DLQ depth > 0:
```typescript
new cloudwatch.Alarm(this, 'ContentJobDlqAlarm', {
  metric: contentJobDlq.metricApproximateNumberOfMessagesVisible(),
  threshold: 1,
  evaluationPeriods: 1,
  alarmDescription: 'Content job failed after 3 retries — check logs',
})
```

---

## Completion Criteria
- [ ] Free users cannot generate more than 5 posts/week or 2 videos/week
- [ ] Setting `CONTENT_GENERATION_ENABLED=false` stops all jobs within 1 minute
- [ ] CloudWatch alarm fires when Bedrock calls exceed threshold
- [ ] DLQ alarm fires when jobs fail repeatedly
- [ ] Storage enforcement runs daily and flags over-limit users
- [ ] No single user can trigger more than 10 content jobs per hour
