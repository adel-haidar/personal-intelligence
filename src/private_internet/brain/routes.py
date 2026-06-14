"""Brain Organiser REST endpoints.

POST /api/brain/organise        -> 202 {run_id, status} | 409 if already running
GET  /api/brain/organise/status -> live status for polling (cheap, in-memory)

Per authenticated user (multi-tenant): a run only ever touches ctx.user_id's
memories, and status reflects that user's run.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from private_internet.brain import organiser
from private_internet.core.request_context import RequestContext, get_request_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brain")


@router.post("/organise")
async def organise(ctx: RequestContext = Depends(get_request_context)):
    try:
        run_id = organiser.start_run(ctx.user_id)
    except organiser.OrganiseAlreadyRunning:
        return JSONResponse(
            status_code=409,
            content={"error": "An organise run is already in progress."},
        )
    logger.info(f"{ctx.log_prefix} brain organise started ({run_id})")
    return JSONResponse(status_code=202, content={"run_id": run_id, "status": "running"})


@router.get("/organise/status")
async def organise_status(ctx: RequestContext = Depends(get_request_context)):
    return organiser.get_status(ctx.user_id)
