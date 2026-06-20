"""Evaluator-optimizer: critique the cover letter and re-draft in a loop.

The evaluator LLM judges a draft against the job and the candidate's real facts;
when it returns REVISE, the worker re-drafts using the evaluator's notes. The
loop runs a small, bounded number of times. The user's own feedback enters the
same machinery via `optimize_loop(initial_notes=..., prior_letter=...)`.
"""

import logging

from assistant.job.application.llm import converse_cached, parse_json_object
from assistant.job.application.models import ApplicationPlan, EvalResult, JobContext
from assistant.job.application.prompts import EVALUATOR_SYSTEM
from assistant.job.application.workers import draft_cover_letter

logger = logging.getLogger(__name__)


def evaluate(
    client,
    model_id: str,
    job: JobContext,
    profile: str,
    plan: ApplicationPlan,
    letter: str,
) -> EvalResult:
    """Judge a draft. Returns PASS on any failure so we never block delivery."""
    key_points = "\n".join(f"- {k}" for k in plan.key_points) or "(none specified)"
    user_text = (
        "=== TARGET JOB ===\n"
        f"Title: {job.title} at {job.company}\n"
        "Description:\n"
        f"{(job.description or '(no description available)')[:5000]}\n\n"
        "=== CANDIDATE PROFILE ===\n"
        f"{profile}\n\n"
        "=== KEY POINTS ===\n"
        f"{key_points}\n\n"
        "=== DRAFT COVER LETTER ===\n"
        f"{letter}\n\n"
        "Evaluate the draft and return the JSON verdict now."
    )
    try:
        data = parse_json_object(
            converse_cached(
                client, model_id, EVALUATOR_SYSTEM, user_text,
                max_tokens=600, temperature=0.0,
            )
        )
    except Exception:
        logger.warning("Evaluator LLM call failed — treating draft as PASS", exc_info=True)
        return EvalResult(verdict="PASS", notes="")

    verdict = str(data.get("verdict") or "PASS").upper()
    if verdict not in ("PASS", "REVISE"):
        verdict = "PASS"
    return EvalResult(verdict=verdict, notes=str(data.get("notes") or ""))


def optimize_loop(
    client,
    model_id: str,
    job: JobContext,
    profile: str,
    plan: ApplicationPlan,
    *,
    max_iterations: int = 2,
    initial_notes: str | None = None,
    prior_letter: str | None = None,
) -> tuple[str, int]:
    """Draft -> evaluate -> revise until PASS or max_iterations. Returns
    (letter, total_draft_count). Blocking."""
    letter = draft_cover_letter(
        client, model_id, job, profile, plan,
        prior_letter=prior_letter, revision_notes=initial_notes,
    )
    iterations = 1

    for _ in range(max(0, max_iterations)):
        result = evaluate(client, model_id, job, profile, plan, letter)
        if result.verdict == "PASS" or not result.notes.strip():
            break
        logger.info("Evaluator requested revision: %s", result.notes[:200])
        letter = draft_cover_letter(
            client, model_id, job, profile, plan,
            prior_letter=letter, revision_notes=result.notes,
        )
        iterations += 1

    return letter, iterations
