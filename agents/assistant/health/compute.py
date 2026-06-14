import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import asyncpg

from assistant.health.db import fetch_metrics, fetch_latest_metric, fetch_source_days
from assistant.health.models import DailyHealthSummary, SourceAvailability, WEIGHT_GOAL_KG

logger = logging.getLogger(__name__)


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _linear_slope(xs: list[float], ys: list[float]) -> Optional[float]:
    """Least-squares slope (equivalent to numpy.polyfit degree=1 slope term)."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


def _day_window(target_date: date, days_back: int) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes covering `days_back` days ending at end of target_date."""
    end = datetime(target_date.year, target_date.month, target_date.day,
                   23, 59, 59, tzinfo=timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(days=days_back)
    return start, end


async def compute_daily_summary(pool: asyncpg.Pool, target_date: date, *, user_id: str) -> DailyHealthSummary:
    """Compute health summary for a given date. All fields optional — never raises on missing data.
    # MUST SCOPE BY USER"""
    try:
        return await _compute(pool, target_date, user_id)
    except Exception:
        logger.exception("Failed to compute health summary for %s", target_date)
        return DailyHealthSummary(date=target_date)


async def _compute(pool: asyncpg.Pool, target_date: date, user_id: str) -> DailyHealthSummary:
    day_start = datetime(target_date.year, target_date.month, target_date.day,
                         0, 0, 0, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    # ── Weight ─────────────────────────────────────────────────────────────

    # Latest weight on target_date or within 2 days prior
    weight_row = await fetch_latest_metric(pool, "weight_kg", day_end, lookback_days=2, user_id=user_id)
    weight_kg = round(weight_row["value"], 2) if weight_row else None

    # 7-day average
    w7_start, w7_end = _day_window(target_date, 7)
    w7_rows = await fetch_metrics(pool, "weight_kg", w7_start, w7_end, user_id=user_id)
    w7_values = [r["value"] for r in w7_rows]
    weight_7day_avg = round(_mean(w7_values), 2) if w7_values else None

    # 14-day trend slope (kg/day → kg/week)
    w14_start, w14_end = _day_window(target_date, 14)
    w14_rows = await fetch_metrics(pool, "weight_kg", w14_start, w14_end, user_id=user_id)

    weight_trend_kg_per_week: Optional[float] = None
    if len(w14_rows) >= 3:
        # x = days since earliest measurement, y = weight
        t0 = w14_rows[0]["recorded_at"]
        xs = [(r["recorded_at"] - t0).total_seconds() / 86400.0 for r in w14_rows]
        ys = [r["value"] for r in w14_rows]
        slope_per_day = _linear_slope(xs, ys)
        if slope_per_day is not None:
            weight_trend_kg_per_week = round(slope_per_day * 7, 3)

    # Goal tracking
    progress_to_goal_kg = round(weight_kg - WEIGHT_GOAL_KG, 2) if weight_kg is not None else None
    weeks_to_goal: Optional[float] = None
    if (
        progress_to_goal_kg is not None
        and weight_trend_kg_per_week is not None
        and weight_trend_kg_per_week < -0.01
        and progress_to_goal_kg > 0
    ):
        weeks_to_goal = round(progress_to_goal_kg / abs(weight_trend_kg_per_week), 1)

    # ── Body fat ────────────────────────────────────────────────────────────

    bf_row = await fetch_latest_metric(pool, "body_fat_percent", day_end, lookback_days=7, user_id=user_id)
    body_fat_percent = round(bf_row["value"], 1) if bf_row else None

    # ── Resting HR ──────────────────────────────────────────────────────────

    hr_row = await fetch_latest_metric(pool, "resting_hr", day_end, lookback_days=1, user_id=user_id)
    resting_hr = round(hr_row["value"], 1) if hr_row else None

    hr7_start, hr7_end = _day_window(target_date, 7)
    hr7_rows = await fetch_metrics(pool, "resting_hr", hr7_start, hr7_end, user_id=user_id)
    hr7_values = [r["value"] for r in hr7_rows]
    resting_hr_7day_avg = round(_mean(hr7_values), 1) if hr7_values else None

    # ── HRV ─────────────────────────────────────────────────────────────────

    hrv_row = await fetch_latest_metric(pool, "hrv_ms", day_end, lookback_days=1, user_id=user_id)
    hrv_ms = round(hrv_row["value"], 1) if hrv_row else None

    # ── Sleep ────────────────────────────────────────────────────────────────

    sleep_rows = await fetch_metrics(pool, "sleep_duration_min", day_start, day_end, user_id=user_id)
    # Take the largest sleep session on this day (the main sleep, not a nap)
    sleep_duration_min: Optional[float] = None
    if sleep_rows:
        sleep_duration_min = round(max(r["value"] for r in sleep_rows), 1)

    score_rows = await fetch_metrics(pool, "sleep_score", day_start, day_end, user_id=user_id)
    sleep_score: Optional[float] = round(max(r["value"] for r in score_rows), 1) if score_rows else None

    # ── Steps ────────────────────────────────────────────────────────────────

    step_rows = await fetch_metrics(pool, "steps", day_start, day_end, user_id=user_id)
    steps: Optional[int] = int(sum(r["value"] for r in step_rows)) if step_rows else None

    # ── Active energy ────────────────────────────────────────────────────────

    energy_rows = await fetch_metrics(pool, "active_energy_kcal", day_start, day_end, user_id=user_id)
    active_energy_kcal: Optional[float] = round(sum(r["value"] for r in energy_rows), 1) if energy_rows else None

    return DailyHealthSummary(
        date=target_date,
        weight_kg=weight_kg,
        weight_7day_avg=weight_7day_avg,
        weight_trend_kg_per_week=weight_trend_kg_per_week,
        body_fat_percent=body_fat_percent,
        resting_hr=resting_hr,
        resting_hr_7day_avg=resting_hr_7day_avg,
        hrv_ms=hrv_ms,
        sleep_duration_min=sleep_duration_min,
        sleep_score=sleep_score,
        steps=steps,
        active_energy_kcal=active_energy_kcal,
        progress_to_goal_kg=progress_to_goal_kg,
        weeks_to_goal_at_current_rate=weeks_to_goal,
    )


# Device sources grouped per physical device. apple_health rows are Apple Watch
# data that arrived via the export.xml route, so both count as the watch.
_DEVICE_SOURCES: dict[str, list[str]] = {
    "beurer_scale": ["beurer_scale"],
    "apple_watch":  ["apple_watch", "apple_health"],
}


def _median_gap_days(days: list[date]) -> int:
    """Median gap in days between consecutive data days. Defaults to 1 (daily)."""
    if len(days) < 2:
        return 1
    gaps = sorted((b - a).days for a, b in zip(days, days[1:]))
    return max(1, gaps[len(gaps) // 2])


async def compute_source_availability(
    pool: asyncpg.Pool,
    target_date: date,
    *,
    user_id: str,
) -> list[SourceAvailability]:
    """For each device source: is there data on target_date, and if not, when is
    new data expected (last data day + the source's observed reporting cadence)?
    # MUST SCOPE BY USER"""
    day_end = datetime(target_date.year, target_date.month, target_date.day,
                       23, 59, 59, tzinfo=timezone.utc) + timedelta(seconds=1)

    result: list[SourceAvailability] = []
    for device, sources in _DEVICE_SOURCES.items():
        days = await fetch_source_days(pool, sources, day_end, days=60, user_id=user_id)
        available = target_date in days
        last_data = max(days) if days else None

        next_expected: Optional[date] = None
        if not available and last_data is not None:
            # Project the next data day from the observed cadence; if that day is
            # already in the past, the earliest realistic arrival is tomorrow.
            projected = last_data + timedelta(days=_median_gap_days(days))
            next_expected = max(projected, target_date + timedelta(days=1))

        result.append(SourceAvailability(
            source=device,
            available=available,
            last_data_date=last_data,
            next_expected_date=next_expected,
        ))
    return result


async def detect_flags(
    pool: asyncpg.Pool,
    summary: DailyHealthSummary,
    history: list[DailyHealthSummary],
    *,
    user_id: str,
) -> list[str]:
    """Rule-based flag detection. No LLM — pure thresholds. # MUST SCOPE BY USER"""
    flags: list[str] = []
    all_days = [summary] + list(history)  # index 0 = today, 1 = yesterday, …

    # goal_reached
    if summary.progress_to_goal_kg is not None and summary.progress_to_goal_kg <= 0:
        flags.append("goal_reached")
        return flags  # other flags irrelevant once goal is reached

    # weight_loss_too_fast
    if (summary.weight_trend_kg_per_week is not None
            and summary.weight_trend_kg_per_week < -1.2):
        flags.append("weight_loss_too_fast")

    # weight_plateau: |trend| < 0.1 for 14+ days while still above goal
    if (summary.weight_trend_kg_per_week is not None
            and abs(summary.weight_trend_kg_per_week) < 0.1
            and (summary.progress_to_goal_kg or 0) > 1.0):
        # Confirm plateau holds across last 14 days of history too
        plateau_days = [
            d for d in all_days
            if d.weight_trend_kg_per_week is not None
            and abs(d.weight_trend_kg_per_week) < 0.1
        ]
        if len(plateau_days) >= 14:
            flags.append("weight_plateau")

    # sleep_below_target: sleep < 7h (420 min) for 2+ consecutive days
    consecutive_short_sleep = 0
    for d in all_days:
        if d.sleep_duration_min is not None and d.sleep_duration_min < 420:
            consecutive_short_sleep += 1
        else:
            break
    if consecutive_short_sleep >= 2:
        flags.append("sleep_below_target")

    # low_hrv_3_days: HRV below 30-day avg by >15% for 3 consecutive days
    if summary.hrv_ms is not None:
        hrv_30day = await _get_30day_hrv_avg(pool, summary.date, user_id=user_id)
        if hrv_30day is not None and hrv_30day > 0:
            threshold = hrv_30day * 0.85
            consecutive_low_hrv = 0
            for d in all_days:
                if d.hrv_ms is not None and d.hrv_ms < threshold:
                    consecutive_low_hrv += 1
                else:
                    break
            if consecutive_low_hrv >= 3:
                flags.append("low_hrv_3_days")

    # resting_hr_elevated: HR > 30-day avg + 5 for 2+ consecutive days
    if summary.resting_hr is not None:
        hr_30day = await _get_30day_hr_avg(pool, summary.date, user_id=user_id)
        if hr_30day is not None:
            threshold = hr_30day + 5
            consecutive_high_hr = 0
            for d in all_days:
                if d.resting_hr is not None and d.resting_hr > threshold:
                    consecutive_high_hr += 1
                else:
                    break
            if consecutive_high_hr >= 2:
                flags.append("resting_hr_elevated")

    return flags


async def _get_30day_hrv_avg(pool: asyncpg.Pool, target_date: date, *, user_id: str) -> Optional[float]:
    day_end = datetime(target_date.year, target_date.month, target_date.day,
                       23, 59, 59, tzinfo=timezone.utc) + timedelta(seconds=1)
    rows = await fetch_metrics(pool, "hrv_ms", day_end - timedelta(days=30), day_end, user_id=user_id)
    values = [r["value"] for r in rows]
    return _mean(values)


async def _get_30day_hr_avg(pool: asyncpg.Pool, target_date: date, *, user_id: str) -> Optional[float]:
    day_end = datetime(target_date.year, target_date.month, target_date.day,
                       23, 59, 59, tzinfo=timezone.utc) + timedelta(seconds=1)
    rows = await fetch_metrics(pool, "resting_hr", day_end - timedelta(days=30), day_end, user_id=user_id)
    values = [r["value"] for r in rows]
    return _mean(values)
