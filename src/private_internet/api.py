from contextlib import asynccontextmanager

from fastapi import FastAPI

from private_internet.auth.oauth import create_oauth_tables
from private_internet.auth.routes import router as auth_router
from private_internet.content.creators import seed_default_creators
from private_internet.content.db import init_content_db
from private_internet.content.router import router as content_router
from private_internet.core.tenancy import migrate_multi_tenancy
from private_internet.memory.mcp_server import mcp
from private_internet.memory.routes import router as memory_router
from private_internet.memory.service import init_db

# Build the MCP sub-app eagerly so the session manager is created before the
# lifespan runs. Starlette does not propagate sub-app lifespans to the parent,
# so we start the session manager's task group here instead.
_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_oauth_tables()
    init_db()
    init_content_db()
    seed_default_creators()
    # Add user_id to every user-data table + seed the admin account. Runs after
    # the base tables exist so the ALTER ... ADD COLUMN statements can find them.
    migrate_multi_tenancy()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Private Internet API", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(content_router)

app.mount("/mcp", _mcp_app)
