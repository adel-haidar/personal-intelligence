from contextlib import asynccontextmanager

from fastapi import FastAPI

from personal_intelligence.auth.oauth import create_oauth_tables
from personal_intelligence.auth.routes import router as auth_router
from personal_intelligence.memory.mcp_server import mcp
from personal_intelligence.memory.routes import router as memory_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_oauth_tables()
    yield


app = FastAPI(title="Personal Intelligence API", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(memory_router)

app.mount("/mcp", mcp.streamable_http_app())
