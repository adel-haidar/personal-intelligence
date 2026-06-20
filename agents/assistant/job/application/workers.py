"""Worker: draft (and re-draft) the cover letter.

The single generative worker in the orchestrator-workers pattern. The same
function produces the first draft, the evaluator-driven revisions, and the
user-feedback revisions — the only difference is whether a previous draft and
revision instructions are supplied.
"""

from assistant.job.application.llm import converse_cached
from assistant.job.application.models import ApplicationPlan, JobContext
from assistant.job.application.prompts import COVER_LETTER_SYSTEM


def draft_cover_letter(
    client,
    model_id: str,
    job: JobContext,
    profile: str,
    plan: ApplicationPlan,
    *,
    prior_letter: str | None = None,
    revision_notes: str | None = None,
) -> str:
    """Write or revise the cover letter. Blocking (boto3)."""
    key_points = "\n".join(f"- {k}" for k in plan.key_points) or "(derive from the profile)"

    user_text = (
        "=== TARGET JOB ===\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location}, {job.country}\n"
        "Description:\n"
        f"{(job.description or '(no description available)')[:5000]}\n\n"
        "=== CANDIDATE PROFILE (from the candidate's brain) ===\n"
        f"{profile}\n\n"
        "=== KEY POINTS TO EMPHASISE ===\n"
        f"{key_points}\n\n"
        f"Desired tone: {plan.tone}"
    )

    if revision_notes:
        if prior_letter and prior_letter.strip():
            user_text += (
                "\n\n=== PREVIOUS DRAFT ===\n"
                f"{prior_letter}\n\n"
                "=== REVISION INSTRUCTIONS ===\n"
                f"{revision_notes}\n\n"
                "Apply the revision instructions to the previous draft and return "
                "the full revised cover letter (plain text only)."
            )
        else:
            user_text += (
                "\n\n=== INSTRUCTIONS ===\n"
                f"{revision_notes}\n\n"
                "Write the cover letter now, incorporating these instructions "
                "(plain text only)."
            )
    else:
        user_text += "\n\nWrite the cover letter now (plain text only)."

    return converse_cached(
        client, model_id, COVER_LETTER_SYSTEM, user_text,
        max_tokens=1200, temperature=0.4,
    ).strip()
