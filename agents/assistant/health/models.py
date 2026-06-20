from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

METRIC_TYPE = Literal[
    "weight_kg",
    "body_fat_percent",
    "resting_hr",
    "hrv_ms",
    "sleep_duration_min",
    "sleep_score",
    "steps",
    "active_energy_kcal",
    "vo2_max",
]

SOURCE = Literal["apple_watch", "apple_health", "beurer_scale", "samsung_health", "manual"]


class HealthMetric(BaseModel):
    id: Optional[int] = None
    recorded_at: datetime
    metric_type: METRIC_TYPE
    value: float
    unit: str
    source: SOURCE
    created_at: Optional[datetime] = None


class DailyHealthSummary(BaseModel):
    date: date
    weight_kg: Optional[float] = None
    weight_7day_avg: Optional[float] = None
    weight_trend_kg_per_week: Optional[float] = None   # negative = losing
    body_fat_percent: Optional[float] = None
    resting_hr: Optional[float] = None
    resting_hr_7day_avg: Optional[float] = None
    hrv_ms: Optional[float] = None
    sleep_duration_min: Optional[float] = None
    sleep_score: Optional[float] = None
    steps: Optional[int] = None
    active_energy_kcal: Optional[float] = None
    progress_to_goal_kg: Optional[float] = None        # current weight minus target; None when goal unknown
    weeks_to_goal_at_current_rate: Optional[float] = None


class SourceAvailability(BaseModel):
    """Data availability for one device source on the target date."""
    source: Literal["beurer_scale", "apple_watch", "samsung_health"]
    available: bool
    last_data_date: Optional[date] = None       # most recent day with any data
    next_expected_date: Optional[date] = None   # when new data should arrive (from cadence)


class HealthInsightResponse(BaseModel):
    date: date
    status: Literal["ok", "not_run"] = "ok"
    summary: DailyHealthSummary
    flags: list[str]
    coach_insight: str
    analysis: str = ""                          # basic analysis from medical records + metrics
    reasoning: str = ""                         # why the analysis says what it says
    documents: list[str] = []                   # mcp-memory documents consulted (titles)
    data_availability: list[SourceAvailability] = []


class ManualEntryRequest(BaseModel):
    recorded_at: datetime
    metric_type: METRIC_TYPE
    value: float
    unit: str
