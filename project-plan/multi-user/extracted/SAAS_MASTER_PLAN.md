# Private Internet — Multi-User SaaS Infrastructure Plan

---

## Answers to Your Two Questions

### 1. Should I create a VPC per user?

**No.** Here is why.

A VPC by itself costs nothing, but everything inside it does. If each user got their own VPC with a dedicated EC2 + RDS, the minimum cost per user would be approximately:

| Resource | Monthly cost |
|----------|-------------|
| EC2 t3.small | ~$17 |
| RDS db.t3.micro | ~$28 |
| Data transfer | ~$5 |
| **Per-user minimum** | **~€50/month** |

At 50 users that is €2,500/month in infrastructure before a single line of business logic runs. That kills the product before it starts.

The correct model — used by Notion, Linear, Vercel, and every serious SaaS — is **shared infrastructure with strict application-level isolation**:

- One VPC, one cluster, one RDS instance — shared
- Data isolated by `user_id` at the database layer (PostgreSQL Row Level Security)
- Files isolated by S3 key prefix: `s3://private-internet/{user_id}/...`
- Content generation jobs scoped per user by the scheduler

This gives you **equivalent security** at a fraction of the cost. At 100 active users the shared stack costs approximately €150–250/month total.

The only case for per-user infrastructure is an **enterprise self-hosted tier** where a company wants Private Internet deployed into their own AWS account. That is a future product offering, not the starting point.

---

### 2. What services are created per user, and how is it automated?

When a user registers, a **lightweight provisioning pipeline** runs automatically. It does not create any new AWS resources — it creates records and namespaces within existing shared infrastructure:

| Step | What happens | Where |
|------|-------------|-------|
| 1 | Insert `users` row | RDS PostgreSQL |
| 2 | Send verification email | Amazon SES |
| 3 | Create S3 namespace | Prefix `{user_id}/` in shared bucket |
| 4 | Seed MCP memory namespace | Existing MCP server |
| 5 | Queue onboarding content job | SQS |
| 6 | Send welcome email | Amazon SES |

This pipeline runs in under 2 seconds. No CloudFormation, no Lambda cold starts, no VPC peering. A FastAPI background task handles it.

---

## Full Architecture

```
                        ┌─────────────────────────────────┐
                        │     Route 53 + ACM               │
                        │  private.internet (wildcard SSL) │
                        └──────────────┬──────────────────┘
                                       │
                        ┌──────────────▼──────────────────┐
                        │        CloudFront CDN            │
                        │  (serves frontend + S3 assets)  │
                        └──────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────┐
                    │              VPC (one, shared)           │
                    │                                          │
                    │  ┌──────────────────────────────────┐   │
                    │  │   ECS Fargate (replaces EC2)      │   │
                    │  │   FastAPI app — auto-scales       │   │
                    │  │   2 tasks min / 10 tasks max      │   │
                    │  └──────────────┬───────────────────┘   │
                    │                 │                        │
                    │  ┌──────────────▼───────────────────┐   │
                    │  │   RDS PostgreSQL (shared)         │   │
                    │  │   Row Level Security per user_id  │   │
                    │  │   RDS Proxy for connection pool   │   │
                    │  └──────────────────────────────────┘   │
                    │                                          │
                    │  ┌───────────────────────────────────┐  │
                    │  │   S3 (shared bucket)               │  │
                    │  │   /{user_id}/posts/                │  │
                    │  │   /{user_id}/videos/               │  │
                    │  │   /{user_id}/health/               │  │
                    │  │   /{user_id}/uploads/              │  │
                    │  └───────────────────────────────────┘  │
                    │                                          │
                    │  SQS · EventBridge · SES · Bedrock      │
                    └─────────────────────────────────────────┘
```

**Why ECS Fargate instead of single EC2?**
A single EC2 works for one user (Adel). For multiple users with concurrent content generation jobs, you need auto-scaling. ECS Fargate scales task count based on CPU/memory load. You pay only for what runs.

---

## Phase Overview

| Phase | Name | Agent | Depends on |
|-------|------|-------|------------|
| **P1** | Infrastructure as Code (CDK) | Claude Code | nothing |
| **P2** | Registration & Email Verification | Claude Code | P1 |
| **P3** | Per-User Provisioning Pipeline | Claude Code | P2 |
| **P4** | Public Landing Page + Pricing | Codex | P1 |
| **P5** | Transactional Email System (SES) | Claude Code | P1 |
| **P6** | Billing & Plans (Stripe) | Claude Code | P2, P5 |
| **P7** | Admin Dashboard | Codex | P2, P3 |
| **P8** | Cost Controls & Usage Limits | Claude Code | P3, P6 |

**P1 must complete first.**
**P2 + P4 + P5 can run in parallel after P1.**
**P3 + P6 require P2.**
**P7 + P8 are last.**

---

## Plans & Pricing Tiers (recommendation)

| Tier | Price | Limits |
|------|-------|--------|
| **Free** | €0 | 50 memories max, 5 posts/week, 2 videos/week, 500MB storage |
| **Personal** | €9/month | Unlimited memories, 20 posts/week, 7 videos/week, 5GB storage |
| **Pro** | €19/month | Unlimited everything, priority generation, 20GB storage |

Enforced at the application layer via a `plans` table and middleware checks. Stripe manages billing. Free tier keeps the product accessible. Pro pays for infra.

---

## See Also
- `saas/PHASE1_CDK_INFRASTRUCTURE.md` → Claude Code
- `saas/PHASE2_REGISTRATION_AUTH.md` → Claude Code
- `saas/PHASE3_USER_PROVISIONING.md` → Claude Code
- `saas/PHASE4_LANDING_PAGE.md` → Codex
- `saas/PHASE5_EMAIL_SES.md` → Claude Code
- `saas/PHASE6_BILLING_STRIPE.md` → Claude Code
- `saas/PHASE7_ADMIN_DASHBOARD.md` → Codex
- `saas/PHASE8_COST_CONTROLS.md` → Claude Code
