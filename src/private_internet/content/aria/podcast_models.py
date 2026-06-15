"""ARIA podcast Pydantic response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

PodcastStatus = Literal["generating", "ready", "failed"]


class DialogueLine(BaseModel):
    host: Literal["A", "B"]
    text: str
    pause_after_ms: int = 400


class PodcastSummaryOut(BaseModel):
    """List-view podcast card (no transcript / audio)."""

    id: str
    title: str
    description: Optional[str] = None
    topic_category: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: PodcastStatus
    art_url: Optional[str] = None
    language_code: str = "en"
    is_liked: bool = False
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_uuid(cls, v):
        return str(v) if v is not None else v


class PodcastDetailOut(PodcastSummaryOut):
    """Detail-view podcast: adds audio/waveform URLs + transcript + hosts."""

    audio_url: Optional[str] = None
    waveform_url: Optional[str] = None
    transcript: list[DialogueLine] = []
    brain_topic_ids: list[str] = []
    host_a_name: str = "Alex"
    host_b_name: str = "Jordan"

    @field_validator("transcript", mode="before")
    @classmethod
    def coerce_transcript(cls, v):
        return v or []

    @field_validator("brain_topic_ids", mode="before")
    @classmethod
    def coerce_brain_topic_ids(cls, v):
        if v is None:
            return []
        return [str(x) for x in v]


class PodcastLikeRequest(BaseModel):
    liked: bool


class PodcastLikeResponse(BaseModel):
    podcast_id: str
    liked: bool


class PodcastStatusOut(BaseModel):
    generating: int = 0
    failed: int = 0
