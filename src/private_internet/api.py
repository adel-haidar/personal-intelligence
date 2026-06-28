import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI

from private_internet.auth.oauth import bootstrap_oauth_user_binding, create_oauth_tables
from private_internet.auth.routes import router as auth_router
from private_internet.billing.coupons import init_coupons_db, seed_tester_coupons
from private_internet.billing.routes import router as billing_router
from private_internet.billing.service import require_feature
from private_internet.brain.db import init_brain_db
from private_internet.brain.routes import router as brain_router
from private_internet.connectors.db import init_connectors_db
from private_internet.connectors.routes import router as connectors_router
from private_internet.bank_link.db import init_bank_link_db
from private_internet.bank_link.routes import router as bank_router
from private_internet.config import get_settings
from private_internet.content.aria.db import init_aria_db
from private_internet.content.aria.podcast_db import init_aria_podcast_db
from private_internet.content.aria.router import router as aria_router
from private_internet.content.aria.voice_config import warn_if_podcast_voices_unconfigured
from private_internet.content.creators import seed_default_creators
from private_internet.content.db import init_content_db
from private_internet.content.router import router as content_router
from private_internet.content.stories.db import init_stories_db
from private_internet.content.stories.router import router as stories_router
from private_internet.core.saas_migration import migrate_saas
from private_internet.core.tenancy import migrate_multi_tenancy
from private_internet.memory.mcp_server import mcp
from private_internet.memory.routes import router as memory_router
from private_internet.memory.service import init_db
from private_internet.sharing.db import init_shares_db
from private_internet.sharing.router import router as sharing_router
from private_internet.users.google_auth import router as google_auth_router
from private_internet.users.routes import router as users_router
from private_internet.users.status_routes import router as user_status_router

logger = logging.getLogger(__name__)

# Build the MCP sub-app eagerly so the session manager is created before the
# lifespan runs. Starlette does not propagate sub-app lifespans to the parent,
# so we start the session manager's task group here instead.
_mcp_app = mcp.streamable_http_app()


def _warn_missing_env() -> None:
    """Surface misconfiguration at boot instead of failing silently later."""
    s = get_settings()
    if not s.secret_key:
        logger.warning(
            "SECRET_KEY is unset — platform JWT login/registration will fail "
            "(legacy OAuth + the dashboard are unaffected)."
        )
    if not s.seed_admin_email:
        logger.warning(
            "SEED_ADMIN_EMAIL is unset — seed admin defaults to admin@%s.", s.app_domain
        )
    if not s.replicate_api_key:
        logger.warning(
            "REPLICATE_API_KEY is not set. SIGNAL and PULSE video generation "
            "will fall back to colour cards (STORIES still uses Kling/fal)."
        )


def _bootstrap_step(name: str, fn) -> None:
    """Run one startup step in isolation. A failure here (e.g. a migration
    error) must NOT take the whole API down — the MCP server, OAuth, and the
    rest of the routes should still serve. The failure is logged loudly so it
    is visible in `journalctl`; affected requests will surface their own errors."""
    try:
        fn()
    except Exception:
        logger.exception(
            "Startup step '%s' FAILED — continuing in degraded mode; features "
            "depending on it may error until this is fixed.", name
        )


async def _nightly_organise_loop() -> None:
    """Run the Brain Organiser for every onboarded user nightly at 02:00 server
    time. Runs are serialized (one user at a time) to avoid a burst of parallel
    Bedrock calls. Disable with BRAIN_ORGANISE_NIGHTLY=false."""
    from private_internet.brain import organiser
    from private_internet.users.service import list_onboarded_user_ids

    while True:
        now = datetime.now()
        nxt = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            for user_id in list_onboarded_user_ids():
                try:
                    organiser.start_run(user_id)
                    while organiser.get_status(user_id)["status"] == "running":
                        await asyncio.sleep(5)
                except organiser.OrganiseAlreadyRunning:
                    continue
                except Exception:
                    logger.exception("nightly organise failed for a user")
        except Exception:
            logger.exception("nightly organise loop iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_missing_env()
    # Order matters: base tables exist before the multi-tenancy migration ALTERs them.
    _bootstrap_step("create_oauth_tables", create_oauth_tables)
    _bootstrap_step("init_db", init_db)
    _bootstrap_step("init_content_db", init_content_db)
    _bootstrap_step("init_aria_db", init_aria_db)
    _bootstrap_step("init_aria_podcast_db", init_aria_podcast_db)
    _bootstrap_step("init_stories_db", init_stories_db)
    _bootstrap_step("init_shares_db", init_shares_db)
    _bootstrap_step("seed_default_creators", seed_default_creators)
    _bootstrap_step("migrate_multi_tenancy", migrate_multi_tenancy)
    # SaaS columns/tables depend on users + content_creators already existing.
    _bootstrap_step("migrate_saas", migrate_saas)
    # OAuth→user binding FK + backfill; needs the `users` table to exist (above).
    _bootstrap_step("bootstrap_oauth_user_binding", bootstrap_oauth_user_binding)
    # Coupons/access codes depend on users existing; seed any TESTER_COUPONS after.
    _bootstrap_step("init_coupons_db", init_coupons_db)
    _bootstrap_step("seed_tester_coupons", seed_tester_coupons)
    # Brain Organiser columns/tables depend on the memories table existing.
    _bootstrap_step("init_brain_db", init_brain_db)
    # Connectors schema depends on the memories table existing (connector_items
    # records memory_id TEXT references from memory/service.py).
    _bootstrap_step("init_connectors_db", init_connectors_db)
    # Bank-link tables (GoCardless): reference memory_id TEXT from memory/service.py.
    _bootstrap_step("init_bank_link_db", init_bank_link_db)
    # Non-fatal: warn (don't fail startup) if podcast voices are still placeholders.
    _bootstrap_step("check_podcast_voices", warn_if_podcast_voices_unconfigured)

    nightly_task = None
    if os.getenv("BRAIN_ORGANISE_NIGHTLY", "true").lower() != "false":
        nightly_task = asyncio.create_task(_nightly_organise_loop())

    async with mcp.session_manager.run():
        yield

    if nightly_task is not None:
        nightly_task.cancel()


app = FastAPI(title="Private Internet API", lifespan=lifespan)


@app.middleware("http")
async def _security_headers(request, call_next):
    """Defense-in-depth response headers for every API response.

    Kept conservative on purpose: no Content-Security-Policy here (it would need
    per-route tuning for /mcp and the OAuth pages). HSTS is ignored by browsers
    over plain HTTP, so it is safe to send unconditionally.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    )
    return response


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(google_auth_router)
app.include_router(user_status_router)
app.include_router(memory_router)
app.include_router(content_router)
# ARIA (music) is Pro+, STORIES is Max — gate the whole router. Cron/admin
# callers resolve to the seed admin (effective plan = max), so timers still run.
app.include_router(aria_router, dependencies=[Depends(require_feature("aria"))])
app.include_router(stories_router, dependencies=[Depends(require_feature("stories"))])
app.include_router(billing_router)
app.include_router(brain_router)
# Connectors (external platform import: Notion, GitHub, Google Drive, …).
# The OAuth callback route carries no auth dependency (provider calls it directly).
app.include_router(connectors_router)
# Bank linking (GoCardless PSD2). The /callback route carries no auth dependency
# (GoCardless redirects the user's browser there); /poll-all uses INTERNAL_SECRET.
app.include_router(bank_router)
# Global sharing. The public GET /api/share/{token} carries no auth dependency
# (it serves only a denormalised snapshot); POST/list/DELETE are per-route auth'd.
app.include_router(sharing_router)

app.mount("/mcp", _mcp_app)
