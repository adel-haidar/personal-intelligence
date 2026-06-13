# Private Internet — Agent Coordination Context

> Companion to the root `CLAUDE.md` (deploy rules + naming split). This file is the
> shared context every subagent inherits. Keep it factually aligned with the code.

## What this project is
**Private Internet** — a self-hostable, privacy-first AI platform. Originally Adel's
single-user system; now being transformed into a multi-user product where every user
gets an isolated AI "brain" (memory) that powers content, health, and financial insight.
Runs on AWS EC2 (eu-central-1) behind nginx + CloudFront, RDS PostgreSQL + pgvector,
AWS Bedrock for inference.

## Naming split (do not "fix")
- **Branding / package:** Private Internet · `private-internet` · Python pkg `private_internet`
- **Infra pointers that KEEP the old name** (renaming breaks deploys): GitHub repo
  `personal-intelligence`, EC2 dir `~/personal-intelligence`, systemd units
  `personal-intelligence-api` / `personal-intelligence-agents`, nginx conf
  `personal-intelligence.conf`, prod domain `adel-intelligence.com` (override per-instance
  with `APP_DOMAIN`).

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic v2 |
| DB driver | **psycopg2** (synchronous) via `database.py::_connect()` — NOT asyncpg |
| LLM | AWS Bedrock — Titan Embed v2 (1024-d embeddings), Claude Haiku + Nova Canvas (content) |
| Frontend | Vue 3 + TypeScript + Vite (composables, **no Pinia store dir**) |
| Database | RDS PostgreSQL 15 + pgvector |
| Auth | OAuth 2.1/PKCE (claude.ai MCP + dashboard) **+ new email/password user auth (JWT)** |
| MCP | FastMCP mounted at `/mcp` on the API process |

## Two deployable services
1. **Service A — `personal-intelligence-api`** (port **8000**, public via nginx)
   Source: `src/private_internet/`. FastAPI + FastMCP in one process. OAuth and the
   old file-upload (formerly port 8002) are **merged in here** — there is no separate
   8002 service anymore.
2. **Service B — `personal-intelligence-agents`** (port **8001**, internal only)
   Source: top-level `agents/`. Email, banking, trading, job, and health agents.

## Real repository layout
```
personal-intelligence/                  (repo dir; product = "Private Internet")
├── src/private_internet/               # Service A
│   ├── api.py                          # app factory + lifespan (runs migrations, mounts /mcp)
│   ├── config.py                       # Pydantic Settings (APP_DOMAIN, SEED_ADMIN_EMAIL, …)
│   ├── database.py                     # psycopg2 _connect() factory
│   ├── auth/                           # OAuth 2.1/PKCE (oauth.py, routes.py)
│   ├── memory/                         # MCP server + pgvector memory (service/routes/mcp_server)
│   ├── content/                        # PULSE + SIGNAL UNIFIED (creators, topics, posts,
│   │                                   #   videos, jobs/, generators); tables are content_*
│   ├── core/                           # tenancy.py (multi-tenant migration), request_context.py,
│   │                                   #   jobs.py (run_for_all_users)
│   └── users/                          # NEW: accounts (service.py) + JWT tokens (tokens.py)
├── agents/                             # Service B (port 8001)
│   ├── main.py
│   └── assistant/{banking,email,health,job,trading,shared}/
├── frontend/src/                       # Vue 3: views/, components/, composables/,
│   │                                   #   config/env.ts (API_BASE), api/, router/, types/
├── migrations/                         # SQL: 0005_multi_tenancy.sql, 001_add_health_metrics.sql
├── systemd/  nginx/  .github/workflows/
└── pyproject.toml                      # package "private-internet"
```

## Multi-tenancy (current state — Sections 0 & 1 DONE)
- Every user-data table has `user_id UUID NOT NULL` (memories, content_*, health_metrics,
  job_matches). `content_creators` is **shared** (no user_id). Migration runs idempotently
  at API startup via `core/tenancy.py` (mirrored in `migrations/0005_multi_tenancy.sql`).
- `core/request_context.RequestContext` (FastAPI `Depends`) resolves the caller: platform
  JWT → its user; legacy OAuth/MCP token → seed admin (`SEED_ADMIN_EMAIL` or `admin@APP_DOMAIN`).
- Scoping convention: every user-data query carries `# MUST SCOPE BY USER` and
  `WHERE user_id = ctx.user_id`. Jobs take a required `user_id` and `assert user_id is not None`.
- `core/jobs.run_for_all_users(job_fn, **kw)` fans pipelines over onboarded users.
- **Next: Section 2** — email/password auth router in `users/` (register/login/me/onboarding),
  password hashing, `REGISTRATION_OPEN`/`MAX_USERS` gating. Must NOT disturb existing OAuth.

## Hard Rules (all agents)
- **Never commit `.env` or secrets.** Secrets come from env vars only.
- **No breaking changes to `/mcp/*` or `/.well-known/*`** — claude.ai + RFC 8414 depend on them.
- **All schema changes need a migration** in `migrations/`; startup bootstrap may mirror it.
- **Deterministic pipelines (bank, health) use `temperature=0`.** Creative content
  generation (PULSE post text) may use higher temperature where the module documents it.
- **Frontend aesthetic:** "Calm Intelligence" — a light/dark design system (indigo
  `--accent-primary`, warm `--brain-amber`, Plus Jakarta Sans / Inter / Lora serif /
  JetBrains Mono). Theme persists, dark is default. Tokens live in
  `frontend/src/styles/tokens.css` (lifted from the Claude Design handoff). This
  **replaced** the old Soviet-bureaucratic dark theme (a personal joke, unfit for a
  public product). No shadows on cards (depth = bg steps + borders); shadows only on
  menus/toasts. The signature element is the amber **Brain Pulse** (4 orbiting dots).
- Ports are fixed: API **8000**, agents **8001**. (The old 8002 auth/file service is retired.)
- After any change, follow the root `CLAUDE.md` commit/deploy rules. The product work lives
  on branch `product/private-internet` — do not push to `main` (it auto-deploys) unless asked.

## Coordination
- `/sprint <goal>` decomposes work into per-domain subagents (see `.claude/commands/sprint.md`).
- Agent docs in `.claude/agents/` define each specialist's domain. `auth-agent`, `infra-agent`,
  and `database-agent` run in `permissionMode: default` (they ask before writing).
- The aspirational "named AI agents" (Ragnarr/Noor/Björn/Freya multi-agent router) is **not
  implemented** — there is no `multi_agent/` module in the codebase today.
