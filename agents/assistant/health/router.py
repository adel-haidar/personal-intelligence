import io
import logging
import os
import tempfile
import zipfile
from datetime import date, datetime, timezone

import boto3
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from functools import lru_cache
from pydantic import BaseModel
from typing import Optional

from assistant.health.compute import _DEVICE_SOURCES, compute_daily_summary
from assistant.health.db import (
    bulk_insert,
    fetch_latest_data_dates,
    fetch_trends,
    get_pool,
    init_pool,
)
from assistant.health.ingest import (
    is_samsung_health_json,
    parse_apple_health_export,
    parse_samsung_health_export,
)
from assistant.health.models import (
    DailyHealthSummary,
    HealthInsightResponse,
    ManualEntryRequest,
    HealthMetric,
    SOURCE,
)
from assistant.health.workflow import fetch_from_mcp_memory, run_daily_health_workflow
from assistant.shared.auth import require_user
from assistant.shared.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

TREND_METRICS = ["weight_kg", "resting_hr", "sleep_duration_min", "steps",
                 "hrv_ms", "active_energy_kcal", "body_fat_percent"]

_seed_admin_id: str | None = None


async def _resolve_user_id(ident: dict, pool) -> str:
    """The effective user_id to scope health data by.  # MUST SCOPE BY USER

    Platform JWT callers → their own user_id. Internal (cron via INTERNAL_SECRET)
    and legacy OAuth callers carry no user_id, so they attribute to the seed admin
    — preserving the owner's existing daily pipeline."""
    if ident.get("user_id"):
        return ident["user_id"]
    global _seed_admin_id
    if _seed_admin_id is None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM users WHERE is_admin = true LIMIT 1")
        if not row:
            raise HTTPException(503, "No admin user to attribute internal health data to")
        _seed_admin_id = str(row["id"])
    return _seed_admin_id


@lru_cache
def _bedrock(region: str):
    return boto3.client("bedrock-runtime", region_name=region)


async def _pool():
    settings = get_settings()
    if not settings.database_url:
        raise HTTPException(503, "DATABASE_URL not configured")
    return await init_pool(settings.database_url)


# ── Import ────────────────────────────────────────────────────────────────────

@router.post("/health/import/apple-health")
async def import_apple_health(
    file: UploadFile = File(...),
    ident: dict = Depends(require_user),
):
    """Accept the Apple Health export — either the raw export.xml OR the
    'Export All Health Data' .zip (which contains apple_health_export/export.xml).
    Streams to /tmp, parses, bulk-inserts new rows for the calling user."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)

    # Stream to temp file to avoid loading 100MB+ into memory
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp_path = tmp.name
        chunk_size = 64 * 1024
        while chunk := await file.read(chunk_size):
            tmp.write(chunk)

    try:
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        os.unlink(tmp_path)

    # The .zip archive starts with the ZIP magic bytes "PK". Extract export.xml
    # from it so users can upload the file Apple gives them without unzipping.
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = [n for n in zf.namelist() if n.endswith("export.xml")]
                if not names:
                    raise HTTPException(
                        400, "That .zip doesn't contain an Apple Health export.xml."
                    )
                xml_bytes = zf.read(names[0])
        except zipfile.BadZipFile:
            raise HTTPException(400, "Could not read that .zip file.")
    else:
        xml_bytes = data

    metrics = parse_apple_health_export(xml_bytes)
    if not metrics:
        return {"inserted": 0, "date_range": [None, None]}

    inserted = await bulk_insert(pool, metrics, user_id=user_id)

    dates = [m.recorded_at.date().isoformat() for m in metrics]
    date_range = [min(dates), max(dates)]

    return {"inserted": inserted, "date_range": date_range}


# ── Samsung Health import ─────────────────────────────────────────────────────

@router.post("/health/import/samsung-health")
async def import_samsung_health(
    file: UploadFile = File(...),
    ident: dict = Depends(require_user),
):
    """Accept a Samsung Health JSON export (or a .zip containing one).

    Samsung Health's "Download personal data" feature produces either a raw JSON
    file or a .zip archive whose top-level contains the JSON.  The endpoint sniffs
    the payload: ZIP magic bytes → extract the first .json entry; otherwise treat
    as raw JSON.  Parses into HealthMetric rows and bulk-inserts for the calling
    user.  Multi-tenancy: every write is scoped to the caller's user_id.
    # MUST SCOPE BY USER
    """
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp_path = tmp.name
        chunk_size = 64 * 1024
        while chunk := await file.read(chunk_size):
            tmp.write(chunk)

    try:
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        os.unlink(tmp_path)

    # ZIP archive → extract the first JSON file inside
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                json_names = [n for n in zf.namelist() if n.lower().endswith(".json")]
                if not json_names:
                    raise HTTPException(
                        400, "That .zip doesn't contain a Samsung Health .json file."
                    )
                json_bytes = zf.read(json_names[0])
        except zipfile.BadZipFile:
            raise HTTPException(400, "Could not read that .zip file.")
    else:
        json_bytes = data

    if not is_samsung_health_json(json_bytes):
        raise HTTPException(
            400,
            "File doesn't look like a Samsung Health export "
            "(expected JSON with a 'daily_summary' key).",
        )

    metrics = parse_samsung_health_export(json_bytes)
    if not metrics:
        return {"inserted": 0, "date_range": [None, None]}

    inserted = await bulk_insert(pool, metrics, user_id=user_id)

    dates = [m.recorded_at.date().isoformat() for m in metrics]
    date_range = [min(dates), max(dates)]

    return {"inserted": inserted, "date_range": date_range}


# ── Manual entry ──────────────────────────────────────────────────────────────

@router.post("/health/manual-entry")
async def manual_entry(
    body: ManualEntryRequest,
    ident: dict = Depends(require_user),
):
    """Insert a single metric with source='manual'. For days when the export is stale."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    from assistant.health.db import insert_one

    metric = HealthMetric(
        recorded_at=body.recorded_at,
        metric_type=body.metric_type,
        value=body.value,
        unit=body.unit,
        source="manual",
    )
    saved = await insert_one(pool, metric, user_id=user_id)
    return {"saved": saved}


# ── Workflow trigger ──────────────────────────────────────────────────────────

@router.post("/health/run-daily/{target_date}", response_model=HealthInsightResponse)
async def run_daily(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Trigger the full workflow for a specific date (used by cron / manual trigger).
    Scopes metric reads to the caller and forwards the caller's token so the summary
    saves to the caller's brain (cron's INTERNAL_SECRET → seed admin, unchanged)."""
    settings = get_settings()
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    bedrock_client = _bedrock(settings.aws_region)

    mcp_url = settings.mcp_memory_url
    # Forward the caller's bearer so MCP memory scopes to the right tenant.
    mcp_token = ident["token"] if mcp_url else None

    return await run_daily_health_workflow(
        target_date=target_date,
        pool=pool,
        bedrock_client=bedrock_client,
        model_id=settings.bedrock_model_id,
        mcp_url=mcp_url,
        mcp_token=mcp_token,
        user_id=user_id,
    )


# ── Fetch previous run ────────────────────────────────────────────────────────

@router.get("/health/daily/{target_date}", response_model=HealthInsightResponse)
async def get_daily(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Return a previously computed daily summary from the caller's MCP memory (no LLM re-run)."""
    settings = get_settings()
    if not settings.mcp_memory_url:
        raise HTTPException(503, "MCP_MEMORY_URL not configured")

    # Forward the caller's token → MCP memory scopes the lookup to their tenant.
    result = await fetch_from_mcp_memory(target_date, settings.mcp_memory_url, ident["token"])
    if not result:
        # Do NOT raise 404 here: CloudFront rewrites 403/404 responses to the
        # SPA's index.html (status 200), so the frontend would receive HTML
        # instead of this error. Return a structured "not run" payload instead.
        return HealthInsightResponse(
            date=target_date,
            status="not_run",
            summary=DailyHealthSummary(date=target_date),
            flags=[],
            coach_insight="",
            reasoning=(
                f"No stored health summary for {target_date.isoformat()} — "
                "the daily workflow has not run for this date yet."
            ),
        )
    return result


# ── Trends ───────────────────────────────────────────────────────────────────

@router.get("/health/trends")
async def get_trends(
    days: int = Query(default=30, ge=1, le=365),
    until: date | None = Query(default=None),
    ident: dict = Depends(require_user),
):
    """Return daily time series for charting: weight, resting_hr, sleep, steps, etc.

    `until` anchors the window's end date (defaults to today) so a previously synced
    export whose newest data has aged out can still be charted."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    series = await fetch_trends(pool, TREND_METRICS, days, until=until, user_id=user_id)
    return {"days": days, "series": series}


# ── Sync status ────────────────────────────────────────────────────────────────

@router.get("/health/status")
async def get_status(ident: dict = Depends(require_user)):
    """Persistent, all-time per-device sync state from the brain.

    Unlike /trends and /daily (both anchored to recent dates), this reflects whether
    a device has *ever* synced and when it was last seen — so the dashboard recognizes
    a previously synced device on every login instead of asking for a fresh import."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    latest = await fetch_latest_data_dates(pool, user_id=user_id)

    sources = []
    overall: date | None = None
    for device, raw_sources in _DEVICE_SOURCES.items():
        days = [latest[s] for s in raw_sources if latest.get(s)]
        last = max(days) if days else None
        if last and (overall is None or last > overall):
            overall = last
        sources.append({
            "source": device,
            "has_data": last is not None,
            "last_data_date": last.isoformat() if last else None,
        })

    return {
        "sources": sources,
        "latest_data_date": overall.isoformat() if overall else None,
    }


# ── Summary (no LLM) ─────────────────────────────────────────────────────────

@router.get("/health/summary/{target_date}", response_model=DailyHealthSummary)
async def get_summary(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Compute and return a daily summary on-demand (no LLM call, no insight)."""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)
    return await compute_daily_summary(pool, target_date, user_id=user_id)


# ── PDF health report ─────────────────────────────────────────────────────────

def _fmt_sleep(minutes: float | None) -> str:
    """Format sleep duration in minutes as 'Xh Ym', e.g. '7h 30m'. Returns '—' if None."""
    if minutes is None:
        return "—"
    h = int(minutes // 60)
    m = int(round(minutes % 60))
    return f"{h}h {m}m" if m else f"{h}h"


def _fmt_optional(value: float | None, decimals: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{suffix}"


def _esc(text: str) -> str:
    """Escape &, <, > for reportlab's Paragraph mini-XML parser.

    LLM-generated analysis text routinely contains characters like '<60 bpm' or
    'rest & recover' that reportlab interprets as markup — an unclosed '<tag'
    raises 'paraparser: syntax error' and 500s the whole report. Escaping the
    dynamic text (never the literal <b> labels we add ourselves) prevents that."""
    from xml.sax.saxutils import escape
    return escape(text or "")


# Human-readable wording for each flag — mirrors the frontend's numberLines switch.
_FLAG_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "low_hrv_3_days": (
        "Watch",
        "Heart-rate variability has been low for several days, which can signal "
        "fatigue or stress. Lighter training and earlier nights are recommended.",
    ),
    "sleep_below_target": (
        "Watch",
        "Sleep has been below target on recent nights. Recovery happens during "
        "sleep — an earlier, more consistent bedtime is advised.",
    ),
    "resting_hr_elevated": (
        "Watch",
        "Resting heart rate is higher than usual, which often follows poor sleep "
        "or added stress.",
    ),
    "weight_loss_too_fast": (
        "Attention",
        "Weight is decreasing rapidly. Rapid loss is hard to sustain and can "
        "cost muscle mass — consider easing the calorie deficit.",
    ),
    "weight_plateau": (
        "Steady",
        "Weight has been stable recently. If a change is the goal, small "
        "consistent adjustments work best.",
    ),
    "goal_reached": (
        "Healthy",
        "Weight goal has been reached. The focus now shifts to maintaining it.",
    ),
}


def _build_pdf(
    target_date: date,
    summary: "DailyHealthSummary",
    flags: list[str],
    coach_insight: str,
    analysis: str,
    reasoning: str,
    has_data: bool,
) -> bytes:
    """Construct a professional, doctor-facing PDF using reportlab platypus."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # ── Colour palette (clinical, muted) ──────────────────────────────────────
    DARK = colors.HexColor("#1A1A2E")
    MID = colors.HexColor("#4A4A6A")
    ACCENT = colors.HexColor("#4A5568")
    LIGHT_BG = colors.HexColor("#F7F8FA")
    RULE = colors.HexColor("#D1D5DB")
    ZEBRA = colors.HexColor("#F0F2F5")
    FLAG_WATCH = colors.HexColor("#92400E")       # amber-800
    FLAG_ATTN = colors.HexColor("#991B1B")         # red-800
    FLAG_GOOD = colors.HexColor("#065F46")         # emerald-800
    FLAG_INFO = colors.HexColor("#1E3A5F")         # slate-800

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.2 * cm,
        title=f"Health Analysis Report — {target_date.isoformat()}",
        author="Private Internet Health Assistant",
    )

    styles = getSampleStyleSheet()

    # ── Custom paragraph styles ───────────────────────────────────────────────
    style_title = ParagraphStyle(
        "ReportTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=DARK,
        alignment=TA_LEFT,
    )
    style_subtitle = ParagraphStyle(
        "ReportSubtitle",
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=MID,
        alignment=TA_LEFT,
        spaceAfter=0,
    )
    style_section = ParagraphStyle(
        "SectionHead",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=DARK,
        spaceBefore=14,
        spaceAfter=4,
    )
    style_body = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=DARK,
        spaceAfter=6,
    )
    style_flag_label = ParagraphStyle(
        "FlagLabel",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=FLAG_INFO,
    )
    style_flag_text = ParagraphStyle(
        "FlagText",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=DARK,
    )
    style_footer = ParagraphStyle(
        "Footer",
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=MID,
        alignment=TA_CENTER,
    )
    style_disclaimer = ParagraphStyle(
        "Disclaimer",
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=MID,
        alignment=TA_CENTER,
        spaceBefore=10,
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story = []

    # ── 1. Header ─────────────────────────────────────────────────────────────
    story.append(Paragraph("Health Analysis Report", style_title))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Report date: {target_date.isoformat()}", style_subtitle))
    story.append(Paragraph(f"Generated: {generated_at}", style_subtitle))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceAfter=10))

    if not has_data:
        story.append(Paragraph("Key Metrics", style_section))
        story.append(
            Paragraph(
                f"No health data is available for {target_date.isoformat()}. "
                "Upload an Apple Watch or Samsung Health export from the Private Internet "
                "dashboard, then run the daily analysis to populate this report.",
                style_body,
            )
        )
    else:
        # ── 2. Key metrics table ───────────────────────────────────────────────
        story.append(Paragraph("Key Metrics", style_section))

        # Weight trend cell — build before the table
        trend_val = summary.weight_trend_kg_per_week
        if trend_val is not None:
            direction = "▼" if trend_val < 0 else ("▲" if trend_val > 0 else "→")
            trend_str = f"{direction} {abs(trend_val):.2f} kg/week"
        else:
            trend_str = "—"

        progress_str = (
            f"{summary.progress_to_goal_kg:+.1f} kg to goal (73.0 kg)"
            if summary.progress_to_goal_kg is not None
            else "—"
        )

        metrics_data = [
            ["Metric", "Value"],
            ["Steps", _fmt_optional(summary.steps, decimals=0) if summary.steps is not None else "—"],
            ["Resting heart rate", _fmt_optional(summary.resting_hr, decimals=0, suffix=" bpm")],
            ["Sleep duration", _fmt_sleep(summary.sleep_duration_min)],
            ["Weight", _fmt_optional(summary.weight_kg, decimals=1, suffix=" kg")],
            ["HRV", _fmt_optional(summary.hrv_ms, decimals=0, suffix=" ms")],
            ["Active energy", _fmt_optional(summary.active_energy_kcal, decimals=0, suffix=" kcal")],
            ["Body fat", _fmt_optional(summary.body_fat_percent, decimals=1, suffix=" %")],
            ["Weight trend", trend_str],
            ["Progress to goal", progress_str],
        ]

        col_w = [doc.width * 0.55, doc.width * 0.45]
        tbl = Table(metrics_data, colWidths=col_w)
        tbl.setStyle(
            TableStyle(
                [
                    # Header row
                    ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("TOPPADDING", (0, 0), (-1, 0), 6),
                    # Zebra rows
                    *[
                        ("BACKGROUND", (0, r), (-1, r), ZEBRA)
                        for r in range(2, len(metrics_data), 2)
                    ],
                    # Data rows
                    ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("TOPPADDING", (0, 1), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TEXTCOLOR", (0, 1), (0, -1), DARK),
                    ("TEXTCOLOR", (1, 1), (1, -1), MID),
                    # Outer border
                    ("BOX", (0, 0), (-1, -1), 0.75, RULE),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.75, RULE),
                    # Subtle inner row lines
                    ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(tbl)

        # ── 3. Flags / observations ────────────────────────────────────────────
        story.append(Paragraph("Observations", style_section))
        story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=6))

        flag_rows = []
        for f in flags:
            if f in _FLAG_DESCRIPTIONS:
                label, text = _FLAG_DESCRIPTIONS[f]
                if label == "Watch":
                    label_color = FLAG_WATCH
                elif label == "Attention":
                    label_color = FLAG_ATTN
                elif label == "Healthy":
                    label_color = FLAG_GOOD
                else:
                    label_color = FLAG_INFO
            else:
                label = "Note"
                text = f.replace("_", " ").capitalize()
                label_color = FLAG_INFO

            label_style = ParagraphStyle(
                f"FL_{f}",
                parent=style_flag_label,
                textColor=label_color,
            )
            flag_rows.append(
                [
                    Paragraph(label, label_style),
                    Paragraph(text, style_flag_text),
                ]
            )

        if flag_rows:
            flag_tbl = Table(
                flag_rows,
                colWidths=[doc.width * 0.14, doc.width * 0.86],
            )
            flag_tbl.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE),
                    ]
                )
            )
            story.append(flag_tbl)
        else:
            story.append(
                Paragraph(
                    "No specific observations flagged for this date. All recent metrics appear within normal range.",
                    style_body,
                )
            )

        # ── 4. Summary / coach insight ─────────────────────────────────────────
        if coach_insight or analysis or reasoning:
            story.append(Paragraph("Summary", style_section))
            story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=6))

        if coach_insight:
            story.append(Paragraph("<b>Coach insight</b>", style_body))
            story.append(Paragraph(_esc(coach_insight), style_body))

        if analysis:
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>Analysis</b>", style_body))
            story.append(Paragraph(_esc(analysis), style_body))

        if reasoning:
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>Clinical reasoning</b>", style_body))
            story.append(Paragraph(_esc(reasoning), style_body))

    # ── 5. Footer ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.75, color=RULE, spaceAfter=8))
    story.append(
        Paragraph(
            "This report was generated by an AI health assistant (Private Internet) "
            "and is intended to support, not replace, professional medical judgment. "
            "Always consult a qualified healthcare professional before acting on this information.",
            style_disclaimer,
        )
    )

    doc.build(story)
    return buf.getvalue()


@router.get("/health/report/{target_date}")
async def health_report(
    target_date: date,
    ident: dict = Depends(require_user),
):
    """Return a professional PDF health report for `target_date`, suitable for sharing
    with a medical professional. Pulls stored MCP analysis (if available) and
    on-demand computed summary + trends — no new LLM calls are made.
    # MUST SCOPE BY USER"""
    settings = get_settings()
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)

    # Fetch stored LLM analysis from MCP memory (same pattern as get_daily).
    stored: "HealthInsightResponse | None" = None
    if settings.mcp_memory_url:
        try:
            stored = await fetch_from_mcp_memory(
                target_date, settings.mcp_memory_url, ident["token"]
            )
        except Exception:
            logger.warning("PDF report: could not fetch MCP memory for %s", target_date, exc_info=True)

    # Compute on-demand summary (needed even when stored analysis exists, to fill
    # any gaps and provide accurate current-day metrics).
    try:
        summary = await compute_daily_summary(pool, target_date, user_id=user_id)
    except Exception:
        logger.warning("PDF report: compute_daily_summary failed for %s", target_date, exc_info=True)
        summary = DailyHealthSummary(date=target_date)

    # Pull 30-day trends so the report has context even if no stored LLM run exists.
    try:
        await fetch_trends(pool, TREND_METRICS, 30, until=target_date, user_id=user_id)
    except Exception:
        logger.warning("PDF report: fetch_trends failed for %s", target_date, exc_info=True)

    # Merge: if a stored result exists, prefer its summary fields and flags.
    if stored and stored.status == "ok":
        # Use the stored summary where it has richer data (e.g. flags + insight text)
        # but fall back to the on-demand summary for any missing metric values.
        merged = stored.summary
        # Backfill nulls in stored summary from live compute
        for field in DailyHealthSummary.model_fields:
            if getattr(merged, field) is None and getattr(summary, field) is not None:
                object.__setattr__(merged, field, getattr(summary, field))
        flags = stored.flags
        coach_insight = stored.coach_insight
        analysis = stored.analysis
        reasoning = stored.reasoning
        has_data = True
    else:
        merged = summary
        flags = []
        coach_insight = ""
        analysis = ""
        reasoning = ""
        # "has data" if any metric is non-null
        has_data = any(
            getattr(summary, f) is not None
            for f in DailyHealthSummary.model_fields
            if f != "date"
        )

    pdf_bytes = _build_pdf(
        target_date=target_date,
        summary=merged,
        flags=flags,
        coach_insight=coach_insight,
        analysis=analysis,
        reasoning=reasoning,
        has_data=has_data,
    )

    filename = f"health-report-{target_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class HealthReportRequest(BaseModel):
    """The analysis the dashboard is currently displaying, posted so the PDF
    matches the screen exactly. Daily analyses are generated live (POST
    /run-daily) and not reliably persisted in MCP memory, so the GET variant's
    server-side fetch usually finds nothing — hence the client sends what it has."""
    summary: Optional[DailyHealthSummary] = None
    flags: list[str] = []
    coach_insight: str = ""
    analysis: str = ""
    reasoning: str = ""


@router.post("/health/report/{target_date}")
async def health_report_from_payload(
    target_date: date,
    body: HealthReportRequest,
    ident: dict = Depends(require_user),
):
    """Render the doctor-facing PDF from the analysis the client is showing.

    The narrative (coach insight / analysis / reasoning / flags) comes straight
    from the posted payload so the PDF mirrors the dashboard. Metric values are
    backfilled from a server-side computed summary for any field the client left
    null. No new LLM calls. # MUST SCOPE BY USER"""
    pool = await _pool()
    user_id = await _resolve_user_id(ident, pool)

    try:
        computed = await compute_daily_summary(pool, target_date, user_id=user_id)
    except Exception:
        logger.warning("PDF report: compute_daily_summary failed for %s", target_date, exc_info=True)
        computed = DailyHealthSummary(date=target_date)

    summary = body.summary or computed
    # Backfill any metric the client left null from the freshly computed summary.
    for field in DailyHealthSummary.model_fields:
        if getattr(summary, field) is None and getattr(computed, field) is not None:
            object.__setattr__(summary, field, getattr(computed, field))

    has_data = bool(
        body.coach_insight or body.analysis or body.reasoning or body.flags
    ) or any(
        getattr(summary, f) is not None
        for f in DailyHealthSummary.model_fields
        if f != "date"
    )

    pdf_bytes = _build_pdf(
        target_date=target_date,
        summary=summary,
        flags=body.flags,
        coach_insight=body.coach_insight,
        analysis=body.analysis,
        reasoning=body.reasoning,
        has_data=has_data,
    )

    filename = f"health-report-{target_date.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
