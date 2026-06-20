"""Background entrypoint that generates (or revises) one job application.

Wires the pieces together: load the job + the candidate's brain, plan the
application (orchestrator), draft+evaluate the cover letter (evaluator-optimizer),
merge the original documents into one PDF, and persist the result. Every failure
is recorded on the application row so the UI can show it instead of polling
forever.
"""

import asyncio
import logging
import re
from typing import Optional

import boto3
from botocore.config import Config

from assistant.job.application.assembler import assemble_pdf
from assistant.job.application.documents import list_uploaded_documents
from assistant.job.application.evaluator import optimize_loop
from assistant.job.application.models import ApplicationPlan, JobContext, SelectedDoc
from assistant.job.application.orchestrator import build_plan
from assistant.job.db import (
    fail_application,
    get_application,
    get_match,
    init_pool,
    save_application_result,
)
from assistant.shared.settings import Settings
from assistant.shared.user_profile import build_user_profile

logger = logging.getLogger(__name__)

# When the user's feedback talks about attachments, re-run the orchestrator so it
# can change which documents are included; otherwise reuse the prior selection.
_DOC_FEEDBACK_RE = re.compile(
    r"\b(certificate|certification|diploma|document|attach|attachment|cv|"
    r"r[ée]sum[ée]|resume|file|reference|transcript|portfolio)\b",
    re.IGNORECASE,
)


def _job_description(match: dict) -> str:
    """The full description if we stored it, else a best-effort fallback assembled
    from the fields we do have (for matches scraped before description was kept)."""
    desc = (match.get("description") or "").strip()
    if desc:
        return desc
    parts = [f"{match.get('title', '')} at {match.get('company', '')}".strip()]
    if match.get("ai_summary"):
        parts.append(match["ai_summary"])
    flags = (match.get("tech_flags") or []) + (match.get("domain_flags") or [])
    if flags:
        parts.append("Relevant skills/areas: " + ", ".join(flags))
    return "\n".join(p for p in parts if p)


def _plan_from_manifest(manifest: Optional[dict], docs_by_name: dict) -> ApplicationPlan:
    """Reconstruct the prior plan so a feedback revision keeps the same document
    selection (unless the feedback asks to change it)."""
    plan_data = (manifest or {}).get("plan") or {}
    selected = []
    for i, d in enumerate(plan_data.get("documents") or []):
        fn = (d.get("filename") or "").strip() if isinstance(d, dict) else ""
        if fn and fn in docs_by_name:
            selected.append(SelectedDoc(
                filename=fn, kind=str(d.get("kind") or "other"),
                order=int(d.get("order", i)) if str(d.get("order", i)).lstrip("-").isdigit() else i,
                reason=str(d.get("reason") or ""),
            ))
    if not selected:
        selected = [SelectedDoc(filename=n, kind="other", order=i)
                    for i, n in enumerate(docs_by_name)]
    return ApplicationPlan(
        cover_letter_needed=True,
        documents=sorted(selected, key=lambda s: s.order),
        key_points=[str(k) for k in (plan_data.get("key_points") or [])],
        tone=str(plan_data.get("tone") or "professional, warm, concise"),
        rationale=str(plan_data.get("rationale") or ""),
    )


def _build_bedrock(settings: Settings):
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=10,
            read_timeout=90,
            retries={"max_attempts": 4, "mode": "adaptive"},
        ),
    )


def _make_memory_client(settings: Settings, token: Optional[str], bedrock):
    if not settings.mcp_memory_url:
        return None
    from assistant.shared.memory_client import MemoryClient

    return MemoryClient(
        bedrock_client=bedrock,
        model_id=settings.bedrock_model_id,
        server_url=settings.mcp_memory_url,
        token=token or settings.internal_secret,
    )


async def generate_application(
    settings: Settings,
    *,
    token: Optional[str],
    user_id: str,
    match_id: int,
    app_id: int,
    feedback: Optional[str] = None,
) -> None:
    """Generate or revise the application for (user, match) and persist it."""
    pool = await init_pool(settings.database_url)
    bedrock = _build_bedrock(settings)
    model_id = settings.bedrock_model_id

    try:
        match = await get_match(pool, match_id, user_id=user_id)
        if match is None:
            await fail_application(pool, app_id, "Job match not found.", user_id=user_id)
            return

        job = JobContext(
            title=match.get("title") or "",
            company=match.get("company") or "",
            location=match.get("location") or "",
            country=match.get("country") or "",
            job_url=match.get("job_url") or "",
            description=_job_description(match),
        )

        memory_client = _make_memory_client(settings, token, bedrock)
        profile = await build_user_profile(memory_client, "job")
        docs = await list_uploaded_documents(memory_client, user_id, settings.upload_dir)
        docs_by_name = {d.filename: d for d in docs}

        existing = await get_application(pool, app_id, user_id=user_id)
        prior_letter = (existing or {}).get("cover_letter")
        prior_manifest = (existing or {}).get("manifest")

        if feedback and prior_manifest and not _DOC_FEEDBACK_RE.search(feedback):
            # Targeted text feedback — keep the same documents, just revise the letter.
            plan = _plan_from_manifest(prior_manifest, docs_by_name)
            letter, iterations = await asyncio.to_thread(
                optimize_loop, bedrock, model_id, job, profile, plan,
                max_iterations=1, initial_notes=feedback, prior_letter=prior_letter,
            )
        else:
            # First generation, or feedback that may change which documents attach.
            plan = await asyncio.to_thread(build_plan, bedrock, model_id, job, profile, docs)
            if not plan.cover_letter_needed and not feedback:
                letter, iterations = "", 0
            else:
                letter, iterations = await asyncio.to_thread(
                    optimize_loop, bedrock, model_id, job, profile, plan,
                    max_iterations=2,
                    initial_notes=feedback,
                    prior_letter=prior_letter if feedback else None,
                )

        pdf, doc_manifest = await asyncio.to_thread(
            assemble_pdf, letter, plan.documents, docs_by_name
        )

        manifest = {
            "documents": doc_manifest,
            "cover_letter_included": bool(letter and letter.strip()),
            "plan": {
                "tone": plan.tone,
                "key_points": plan.key_points,
                "rationale": plan.rationale,
                "documents": [s.model_dump() for s in plan.documents],
            },
        }

        await save_application_result(
            pool, app_id, user_id=user_id, pdf=pdf,
            cover_letter=letter, manifest=manifest, iterations=iterations,
        )
        logger.info(
            "Application %s ready for user %s (match %s, %d doc(s), %d iteration(s))",
            app_id, user_id, match_id, len(doc_manifest), iterations,
        )
    except Exception as exc:  # noqa: BLE001 — record the failure, never crash the task
        logger.exception("Application generation failed (app_id=%s)", app_id)
        try:
            await fail_application(
                pool, app_id, f"{type(exc).__name__}: {exc}", user_id=user_id
            )
        except Exception:
            logger.exception("Could not record application failure")
