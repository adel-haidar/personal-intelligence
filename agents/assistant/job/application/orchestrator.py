"""Orchestrator: turn a job + profile + documents into an application plan.

This is the "orchestrator" half of the orchestrator-workers pattern: it decides
WHAT the application should contain and delegates the actual cover-letter writing
to the worker in `workers.py`.
"""

import logging

from assistant.job.application.llm import converse_cached, parse_json_object
from assistant.job.application.models import (
    ApplicationPlan,
    AvailableDoc,
    JobContext,
    SelectedDoc,
)
from assistant.job.application.prompts import ORCHESTRATOR_SYSTEM

logger = logging.getLogger(__name__)


def _format_documents(docs: list[AvailableDoc]) -> str:
    if not docs:
        return "(no uploaded documents found in the candidate's brain)"
    lines = []
    for d in docs:
        excerpt = (d.text_excerpt or "").strip()[:600]
        lines.append(
            f"- filename: {d.filename} (type: {d.ext or 'unknown'})\n"
            f"  excerpt: {excerpt or '(no extractable text)'}"
        )
    return "\n".join(lines)


def build_plan(
    client,
    model_id: str,
    job: JobContext,
    profile: str,
    docs: list[AvailableDoc],
) -> ApplicationPlan:
    """Ask the orchestrator LLM for a structured application plan. Blocking."""
    user_text = (
        "=== TARGET JOB ===\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location}, {job.country}\n"
        "Description:\n"
        f"{(job.description or '(no description available)')[:6000]}\n\n"
        "=== CANDIDATE PROFILE (from the candidate's brain) ===\n"
        f"{profile}\n\n"
        "=== UPLOADED DOCUMENTS ===\n"
        f"{_format_documents(docs)}\n\n"
        "Produce the application plan as a single JSON object now."
    )

    try:
        raw = converse_cached(
            client, model_id, ORCHESTRATOR_SYSTEM, user_text,
            max_tokens=1500, temperature=0.0,
        )
        data = parse_json_object(raw)
    except Exception:
        logger.warning("Orchestrator LLM call failed — using a default plan", exc_info=True)
        data = {}

    available = {d.filename: d for d in docs}
    selected: list[SelectedDoc] = []
    for i, d in enumerate(data.get("documents") or []):
        if not isinstance(d, dict):
            continue
        fn = (d.get("filename") or "").strip()
        if fn in available:
            selected.append(
                SelectedDoc(
                    filename=fn,
                    kind=str(d.get("kind") or "other"),
                    order=int(d.get("order", i)) if str(d.get("order", i)).lstrip("-").isdigit() else i,
                    reason=str(d.get("reason") or ""),
                )
            )

    # If the model selected nothing usable but the user has documents, attach them
    # all rather than producing a letter-only application.
    if not selected and docs:
        selected = [
            SelectedDoc(filename=d.filename, kind="other", order=i)
            for i, d in enumerate(docs)
        ]

    return ApplicationPlan(
        cover_letter_needed=bool(data.get("cover_letter_needed", True)),
        documents=sorted(selected, key=lambda s: s.order),
        key_points=[str(k) for k in (data.get("key_points") or []) if str(k).strip()][:8],
        tone=str(data.get("tone") or "professional, warm, concise"),
        rationale=str(data.get("rationale") or ""),
    )
