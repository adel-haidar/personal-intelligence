import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from private_internet.auth.oauth import create_oauth_tables
from private_internet.auth.routes import router as auth_router
from private_internet.billing.routes import router as billing_router
from private_internet.config import get_settings
from private_internet.content.creators import seed_default_creators
from private_internet.content.db import init_content_db
from private_internet.content.router import router as content_router
from private_internet.core.saas_migration import migrate_saas
from private_internet.core.tenancy import migrate_multi_tenancy
from private_internet.memory.mcp_server import mcp
from private_internet.memory.routes import router as memory_router
from private_internet.memory.service import init_db
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_missing_env()
    # Order matters: base tables exist before the multi-tenancy migration ALTERs them.
    _bootstrap_step("create_oauth_tables", create_oauth_tables)
    _bootstrap_step("init_db", init_db)
    _bootstrap_step("init_content_db", init_content_db)
    _bootstrap_step("seed_default_creators", seed_default_creators)
    _bootstrap_step("migrate_multi_tenancy", migrate_multi_tenancy)
    # SaaS columns/tables depend on users + content_creators already existing.
    _bootstrap_step("migrate_saas", migrate_saas)
    async with mcp.session_manager.run():
        yield


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
app.include_router(user_status_router)
app.include_router(memory_router)
app.include_router(content_router)
app.include_router(billing_router)

app.mount("/mcp", _mcp_app)
