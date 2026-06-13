import hashlib
import io
import datetime
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from private_internet.config import get_settings
from private_internet.core.request_context import RequestContext, get_request_context
from private_internet.memory.service import (
    count_memories,
    delete_memory,
    list_memories,
    save_memory,
    search_memories,
    update_memory,
)

router = APIRouter(prefix="/api")

# All endpoints below operate on the authenticated user's brain only.
# MUST SCOPE BY USER


class SaveTextRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = []


class UpdateMemoryRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    append_content: bool = False


@router.post("/memory/text")
async def save_text_memory(
    body: SaveTextRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    memory = save_memory(
        title=body.title, content=body.content, tags=body.tags, user_id=ctx.user_id
    )
    return {"memory_id": memory.memory_id}


@router.get("/memory")
async def list_memory(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    ctx: RequestContext = Depends(get_request_context),
):
    items, total = list_memories(page=page, page_size=page_size, query=q, user_id=ctx.user_id)
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": items, "total": total, "page": page, "pages": pages}


@router.get("/memory/search")
async def semantic_search_memory(
    q: str,
    k: int = 10,
    ctx: RequestContext = Depends(get_request_context),
):
    """Semantic (vector) search over memory CONTENT — ranked by embedding
    similarity, not title/tag substring. Returns full memories so workflows
    (health, bank adviser, …) can retrieve by *meaning*, not by filename.
    """
    k = max(1, min(k, 50))
    results = search_memories(q, user_id=ctx.user_id, limit=k)
    return {
        "items": [
            {
                "memory_id": m.memory_id,
                "title": m.title,
                "content": m.content,
                "tags": m.tags,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in results
        ]
    }


@router.get("/memory/stats")
async def memory_stats(ctx: RequestContext = Depends(get_request_context)):
    """Brain size + freshness — powers the dashboard and memory-impact panel."""
    total, last = count_memories(user_id=ctx.user_id)
    return {
        "total": total,
        "last_updated": last.isoformat() if last else None,
    }


@router.patch("/memory/{memory_id}")
async def update_memory_endpoint(
    memory_id: str,
    body: UpdateMemoryRequest,
    ctx: RequestContext = Depends(get_request_context),
):
    memory = update_memory(
        memory_id,
        title=body.title,
        content=body.content,
        tags=body.tags,
        append_content=body.append_content,
        user_id=ctx.user_id,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {
        "memory_id": memory.memory_id,
        "title": memory.title,
        "content": memory.content,
        "tags": memory.tags,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


@router.delete("/memory/{memory_id}")
async def delete_memory_endpoint(
    memory_id: str,
    ctx: RequestContext = Depends(get_request_context),
):
    deleted = delete_memory(memory_id, user_id=ctx.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"deleted": True, "memory_id": memory_id}


_PDF_CHUNK_SIZE = 4000


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _chunk_text(text: str) -> list[str]:
    if len(text) <= _PDF_CHUNK_SIZE:
        return [text]
    chunks = []
    while text:
        if len(text) <= _PDF_CHUNK_SIZE:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, _PDF_CHUNK_SIZE)
        if split_at <= 0:
            split_at = _PDF_CHUNK_SIZE
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return chunks


async def _save_uploaded_file(file: UploadFile, upload_dir: str, user_id: str) -> dict:
    content = await file.read()

    if not content:
        return {"error": "Empty file", "filename": file.filename}

    file_hash = hashlib.sha256(content).hexdigest()[:12]
    timestamp = datetime.datetime.now().isoformat()
    filename = f"{file_hash}_{file.filename}"
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

    if ext == "pdf":
        text = _extract_pdf_text(content)
        chunks = _chunk_text(text)
        total = len(chunks)
        first_saved = None
        for i, chunk in enumerate(chunks):
            title = file.filename if total == 1 else f"{file.filename} ({i + 1}/{total})"
            saved = save_memory(
                title=title, content=chunk, tags=["file-upload", "pdf"], user_id=user_id
            )
            if first_saved is None:
                first_saved = saved
    else:
        first_saved = save_memory(
            title=f"Uploaded file: {file.filename}",
            content=(
                f"File uploaded at {timestamp}. "
                f"Path: {filepath}. Size: {len(content)} bytes. "
                f"Hash: {file_hash}."
            ),
            tags=["file-upload", ext],
            user_id=user_id,
        )

    return {
        "status": "ok",
        "memory_id": first_saved.memory_id,
        "filename": filename,
        "size": len(content),
    }


@router.post("/file")
async def upload_file(
    files: list[UploadFile],
    ctx: RequestContext = Depends(get_request_context),
):
    upload_dir = os.path.join(get_settings().upload_dir, ctx.user_id)
    os.makedirs(upload_dir, exist_ok=True)

    results = [await _save_uploaded_file(f, upload_dir, ctx.user_id) for f in files]

    return {"status": "ok", "count": len(results), "files": results}
