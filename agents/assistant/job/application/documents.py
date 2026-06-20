"""Discover the user's uploaded documents (CV, certificates, …).

Combines two sources that Service A produces on upload:
  - the brain: each uploaded file is stored as one or more `file-upload` tagged
    memories whose title is the original filename (chunked files get a
    " (1/3)" suffix). These give us the extracted text for the orchestrator to
    classify each document.
  - the disk: the original file is kept at
    `{upload_dir}/{user_id}/{sha256[:12]}_{original_filename}`. We need the
    original PDF bytes to merge them into the application verbatim.
"""

import logging
import os
import re

from assistant.job.application.models import AvailableDoc

logger = logging.getLogger(__name__)

# Strip a trailing chunk marker like " (2/3)" added to multi-chunk uploads.
_CHUNK_SUFFIX_RE = re.compile(r"\s*\(\d+\s*/\s*\d+\)\s*$")
# Per-document excerpt cap fed to the orchestrator LLM (classification only).
_MAX_EXCERPT = 1500


def _base_filename(title: str) -> str:
    return _CHUNK_SUFFIX_RE.sub("", title or "").strip()


def _has_file_upload_tag(tags) -> bool:
    if isinstance(tags, str):
        return "file-upload" in tags
    if isinstance(tags, (list, tuple)):
        return any("file-upload" in str(t) for t in tags)
    return False


async def list_uploaded_documents(
    memory_client, user_id: str, upload_dir: str
) -> list[AvailableDoc]:
    """Return the user's uploaded documents with text excerpts and disk paths.

    Never raises — on any failure it returns whatever it could gather (possibly
    an empty list), so application generation degrades gracefully.
    """
    # 1. Brain memories for uploaded files, grouped by original filename.
    grouped: dict[str, dict] = {}
    if memory_client is not None:
        try:
            items = await memory_client._list_memories_api(query="file-upload")
        except Exception:
            logger.warning("Could not list uploaded-file memories", exc_info=True)
            items = []
        for it in items:
            if not _has_file_upload_tag(it.get("tags")):
                continue
            base = _base_filename(it.get("title") or "")
            if not base or base.startswith("Uploaded file:"):
                continue
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
            g = grouped.setdefault(base, {"ext": ext, "parts": []})
            g["parts"].append((it.get("title") or base, it.get("content") or ""))

    # 2. Original files on disk, keyed by their original filename (hash stripped).
    disk_map: dict[str, str] = {}
    user_dir = os.path.join(upload_dir, user_id)
    try:
        for fn in os.listdir(user_dir):
            # Disk name is "{hash}_{original}". The hash has no underscore, so a
            # single split recovers the original (which may itself contain "_").
            original = fn.split("_", 1)[1] if "_" in fn else fn
            disk_map.setdefault(original, os.path.join(user_dir, fn))
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("Could not list upload dir %s", user_dir, exc_info=True)

    docs: list[AvailableDoc] = []
    for base, g in grouped.items():
        # Order chunks by their titled suffix so the excerpt reads in order.
        text = "\n".join(content for _, content in sorted(g["parts"], key=lambda p: p[0]))
        docs.append(
            AvailableDoc(
                filename=base,
                ext=g["ext"],
                disk_path=disk_map.get(base),
                text_excerpt=text[:_MAX_EXCERPT],
            )
        )
    logger.info("Found %d uploaded document(s) for user %s", len(docs), user_id)
    return docs
