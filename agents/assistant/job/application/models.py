"""Pydantic contracts for the application generator pipeline."""

from typing import Optional

from pydantic import BaseModel, Field


class JobContext(BaseModel):
    """The job a user is applying to, assembled from the job_matches row."""

    title: str
    company: str
    location: str = ""
    country: str = ""
    job_url: str = ""
    description: str = ""


class AvailableDoc(BaseModel):
    """An uploaded document found in the user's brain + on disk."""

    filename: str          # original filename (brain memory title)
    ext: str               # lowercase extension, e.g. 'pdf'
    disk_path: Optional[str] = None   # absolute path to the original file, if present
    text_excerpt: str = ""            # extracted text (truncated) for the LLM to classify


class SelectedDoc(BaseModel):
    """A document the orchestrator chose to attach to the application."""

    filename: str
    kind: str = "other"     # 'cv' | 'certificate' | 'cover_letter_source' | 'other'
    order: int = 0          # attach order after the cover letter (ascending)
    reason: str = ""


class ApplicationPlan(BaseModel):
    """The orchestrator's plan for one application."""

    cover_letter_needed: bool = True
    documents: list[SelectedDoc] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    tone: str = "professional, warm, concise"
    rationale: str = ""


class EvalResult(BaseModel):
    """The evaluator's verdict on a cover-letter draft."""

    verdict: str = "PASS"   # 'PASS' | 'REVISE'
    notes: str = ""
