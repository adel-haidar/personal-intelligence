import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from assistant.health.models import HealthMetric

logger = logging.getLogger(__name__)

# Apple Health type → our metric_type
_HK_MAP: dict[str, str] = {
    "HKQuantityTypeIdentifierBodyMass":                        "weight_kg",
    "HKQuantityTypeIdentifierBodyFatPercentage":               "body_fat_percent",
    "HKQuantityTypeIdentifierRestingHeartRate":                "resting_hr",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":        "hrv_ms",
    "HKQuantityTypeIdentifierStepCount":                       "steps",
    "HKQuantityTypeIdentifierActiveEnergyBurned":              "active_energy_kcal",
    "HKQuantityTypeIdentifierVO2Max":                          "vo2_max",
    "HKCategoryTypeIdentifierSleepAnalysis":                   "sleep_duration_min",
}

# Source tokens that indicate Beurer scale data
_BEURER_TOKENS = {"beurer", "healthmanager"}

# Sleep values that count as actual sleep (not just in-bed)
_SLEEP_ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepREM",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisInBed",
}

_UNIT_DEFAULTS: dict[str, str] = {
    "weight_kg":         "kg",
    "body_fat_percent":  "%",
    "resting_hr":        "count/min",
    "hrv_ms":            "ms",
    "sleep_duration_min": "min",
    "sleep_score":       "score",
    "steps":             "count",
    "active_energy_kcal": "kcal",
    "vo2_max":           "mL/min·kg",
}


def _parse_dt(s: str) -> Optional[datetime]:
    """Parse Apple Health date string: '2024-01-15 08:30:00 +0100'."""
    if not s:
        return None
    try:
        # Replace the space-offset with a colon-less offset for fromisoformat
        # Apple Health format: '2024-01-15 08:30:00 +0100'
        s = s.strip()
        # Normalize offset: ' +0100' → '+01:00'
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S%z"):
            try:
                return datetime.strptime(s, fmt).astimezone(timezone.utc)
            except ValueError:
                continue
        return None
    except Exception:
        return None


def _detect_source(source_name: str, hk_type: str) -> str:
    src_lower = source_name.lower()
    if any(t in src_lower for t in _BEURER_TOKENS):
        return "beurer_scale"
    if "watch" in src_lower:
        return "apple_watch"
    return "apple_health"


def _convert_to_metric(value: float, unit: str, metric_type: str) -> tuple[float, str]:
    """Convert non-metric units to metric where needed."""
    unit_lower = unit.lower()
    if metric_type == "weight_kg" and unit_lower in ("lb", "lbs"):
        return round(value * 0.453592, 3), "kg"
    if metric_type == "body_fat_percent" and unit_lower == "%":
        return value, "%"
    if metric_type == "resting_hr" and unit_lower in ("count/min", "bpm"):
        return value, "count/min"
    return value, unit


def parse_apple_health_export(xml_bytes: bytes) -> list[HealthMetric]:
    """Parse Apple Health export.xml using iterparse (streaming — handles 100MB+ files).

    Accumulates step count and active energy per day (since Apple records many small
    intervals), then emits one summed row per day. All other metric types take the
    raw individual readings.
    """
    metrics: list[HealthMetric] = []

    # Accumulators for metrics that need daily summing
    daily_steps: dict[str, float] = defaultdict(float)           # day_iso → total
    daily_energy: dict[str, float] = defaultdict(float)
    daily_sleep: dict[str, float] = defaultdict(float)           # night_date → total minutes

    # Track source for accumulated metrics (last seen wins — usually consistent)
    daily_steps_source: dict[str, str] = {}
    daily_energy_source: dict[str, str] = {}
    daily_sleep_source: dict[str, str] = {}

    # Stream-parse straight from the in-memory export bytes.
    import io
    context = ET.iterparse(io.BytesIO(xml_bytes), events=("start",))

    for _event, elem in context:
        if elem.tag != "Record":
            elem.clear()
            continue

        hk_type = elem.get("type", "")
        metric_type = _HK_MAP.get(hk_type)
        if metric_type is None:
            elem.clear()
            continue

        source_name = elem.get("sourceName", "")
        source = _detect_source(source_name, hk_type)

        if metric_type == "sleep_duration_min":
            # Sleep records have startDate + endDate, no numeric value attr
            value_str = elem.get("value", "")
            if value_str not in _SLEEP_ASLEEP_VALUES:
                elem.clear()
                continue
            start_dt = _parse_dt(elem.get("startDate", ""))
            end_dt = _parse_dt(elem.get("endDate", ""))
            if not start_dt or not end_dt:
                elem.clear()
                continue
            duration_min = (end_dt - start_dt).total_seconds() / 60.0
            if duration_min <= 0:
                elem.clear()
                continue
            # Assign sleep to the calendar date of the *start* of the night
            # (if sleep started before midnight, assign to that day)
            night_date = start_dt.date().isoformat()
            daily_sleep[night_date] += duration_min
            daily_sleep_source[night_date] = source
            elem.clear()
            continue

        value_str = elem.get("value", "")
        try:
            raw_value = float(value_str)
        except (ValueError, TypeError):
            elem.clear()
            continue

        start_date_str = elem.get("startDate") or elem.get("creationDate", "")
        recorded_at = _parse_dt(start_date_str)
        if not recorded_at:
            elem.clear()
            continue

        unit = elem.get("unit", _UNIT_DEFAULTS.get(metric_type, ""))
        value, unit = _convert_to_metric(raw_value, unit, metric_type)

        if metric_type == "steps":
            day_iso = recorded_at.date().isoformat()
            daily_steps[day_iso] += value
            daily_steps_source[day_iso] = source
        elif metric_type == "active_energy_kcal":
            day_iso = recorded_at.date().isoformat()
            daily_energy[day_iso] += value
            daily_energy_source[day_iso] = source
        else:
            metrics.append(HealthMetric(
                recorded_at=recorded_at,
                metric_type=metric_type,
                value=round(value, 4),
                unit=unit,
                source=source,
            ))

        elem.clear()

    # Emit summed daily accumulations at noon UTC on each day
    for day_iso, total in daily_steps.items():
        dt = datetime.fromisoformat(f"{day_iso}T12:00:00+00:00")
        metrics.append(HealthMetric(
            recorded_at=dt,
            metric_type="steps",
            value=round(total),
            unit="count",
            source=daily_steps_source.get(day_iso, "apple_health"),
        ))

    for day_iso, total in daily_energy.items():
        dt = datetime.fromisoformat(f"{day_iso}T12:00:00+00:00")
        metrics.append(HealthMetric(
            recorded_at=dt,
            metric_type="active_energy_kcal",
            value=round(total, 2),
            unit="kcal",
            source=daily_energy_source.get(day_iso, "apple_health"),
        ))

    for day_iso, total_min in daily_sleep.items():
        dt = datetime.fromisoformat(f"{day_iso}T22:00:00+00:00")
        metrics.append(HealthMetric(
            recorded_at=dt,
            metric_type="sleep_duration_min",
            value=round(total_min, 1),
            unit="min",
            source=daily_sleep_source.get(day_iso, "apple_health"),
        ))
        # Compute sleep score proxy: min(100, duration/480 * 100)
        score = min(100.0, (total_min / 480.0) * 100.0)
        metrics.append(HealthMetric(
            recorded_at=dt,
            metric_type="sleep_score",
            value=round(score, 1),
            unit="score",
            source=daily_sleep_source.get(day_iso, "apple_health"),
        ))

    logger.info("Parsed %d health metrics from Apple Health export", len(metrics))
    return metrics
