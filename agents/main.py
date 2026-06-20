import json
import logging
import httpx
import boto3
import os

from calendar import monthrange
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from assistant.banking.bank_adviser import BankAdviser
from assistant.banking.investment_adviser import InvestmentAdviser
from assistant.banking.models import BankAdviserResult
from assistant.trading.day_trader import DayTrader
from assistant.trading.market_data import collect_market_snapshot
from assistant.health.router import router as health_router
from assistant.job.router import router as job_router
from assistant.shared.auth import require_user
from assistant.shared.memory_client import MemoryClient
from assistant.shared.settings import Settings, get_settings
from assistant.shared.user_profile import build_user_profile

logger = logging.getLogger(__name__)
app = FastAPI()
app.include_router(job_router, prefix="/api/jobs")
app.include_router(health_router, prefix="/api")


class AnalyseRequest(BaseModel):
    context: str = ""
    mode: Literal["ytd", "single", "range"] = "ytd"
    period_from: str | None = None  # "YYYY-MM"
    period_to: str | None = None    # "YYYY-MM"


def resolve_period(
    mode: str,
    period_from: str | None,
    period_to: str | None,
) -> list[str]:
    """Return list of 'YYYY-MM' strings for the requested range."""
    today = date.today()

    if mode == "ytd":
        start = date(today.year, 1, 1)
        end   = date(today.year, today.month, 1)
    elif mode == "single":
        if not period_from:
            raise ValueError("period_from required for mode=single")
        start = end = datetime.strptime(period_from, "%Y-%m").date()
    elif mode == "range":
        if not period_from or not period_to:
            raise ValueError("period_from and period_to required for mode=range")
        start = datetime.strptime(period_from, "%Y-%m").date()
        end   = datetime.strptime(period_to,   "%Y-%m").date()
    else:
        raise ValueError(f"Unknown mode: {mode}")

    months: list[str] = []
    current = start
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months

# Type alias that tells FastAPI how to inject the Settings dependency into route
# functions. When a route function declares a parameter of this type, FastAPI
# automatically calls get_settings and passes the result in.
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_fresh_token() -> str:
    """Same-host auth to the memory API uses the shared INTERNAL_SECRET, which
    Service A resolves to the seed admin. Stable — no OAuth token to refresh,
    rotate, or harvest from a browser."""
    secret = os.environ.get("INTERNAL_SECRET")
    if not secret:
        raise RuntimeError("INTERNAL_SECRET is not configured")
    return secret


def _make_memory_client(settings: Settings, token: str | None = None) -> MemoryClient:
    """Build a MemoryClient (raises 503 if MCP_MEMORY_URL is unconfigured).

    `token` is the bearer token forwarded to Service A's per-user memory API. Pass
    the caller's own token (from `require_user`) for per-user scoping; falls back
    to the INTERNAL_SECRET (→ seed admin) for owner-scoped / internal callers.
    """
    if not settings.mcp_memory_url:
        raise HTTPException(
            status_code=503,
            detail="MCP_MEMORY_URL is not configured.",
        )
    return MemoryClient(
        bedrock_client=_get_bedrock_client(settings.aws_region),
        model_id=settings.bedrock_model_id,
        server_url=settings.mcp_memory_url,
        token=token or get_fresh_token(),
    )


@lru_cache
def _get_bedrock_client(region: str):
    """Create a boto3 Bedrock client for the given AWS region, cached per region.

    boto3 clients are thread-safe and relatively expensive to create, so we
    cache one per region rather than creating a new one on every request.

    Args:
        region: The AWS region string, e.g. 'eu-central-1'.

    Returns:
        A boto3 `bedrock-runtime` client.
    """
    return boto3.client("bedrock-runtime", region_name=region)


@app.get("/")
def health():
    """Health check endpoint.

    Returns a simple JSON response to confirm the server is running.
    Useful for load balancers or uptime monitors.
    """
    return {"status": "ok"}


@app.post("/api/banking/analyse", response_model=BankAdviserResult)
async def analyse_bank_statement(req: AnalyseRequest, settings: SettingsDep, ident: dict = Depends(require_user)):
    """Run a multi-month financial analysis using bank statements from MCP memory.

    Accepts an explicit period (ytd / single / range), searches MCP once per month
    in the range, feeds all results to the LLM, and returns a holistic analysis.

    Raises:
        HTTPException (400): If the request period params are invalid.
        HTTPException (404): If no bank statements are found for the requested period.
        HTTPException (503): If MCP_MEMORY_URL is not configured.
    """
    if not settings.mcp_memory_url:
        raise HTTPException(
            status_code=503,
            detail="MCP_MEMORY_URL is not configured — bank statement cannot be sourced.",
        )

    try:
        months = resolve_period(req.mode, req.period_from, req.period_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    bedrock_client = _get_bedrock_client(settings.aws_region)
    memory_client = MemoryClient(
        bedrock_client=bedrock_client,
        model_id=settings.bedrock_model_id,
        server_url=settings.mcp_memory_url,
        token=ident["token"],
    )

    all_statements: list[str] = []
    missing_months: list[str] = []

    for month in months:
        # A timeout/error fetching one month must not 500 the whole analysis —
        # treat it as a missing month and continue (memory ops can be slow when
        # the box is busy embedding/generating).
        try:
            content = await memory_client.fetch_bank_statement_for_month(month)
        except Exception:
            logger.warning("Failed to fetch bank statement for %s — treating as missing", month, exc_info=True)
            content = ""
        if content:
            all_statements.append(f"=== BANK STATEMENT {month} ===\n{content}")
        else:
            missing_months.append(month)

    if not all_statements:
        # NOT 404: CloudFront is configured SPA-style to rewrite 403/404 origin
        # responses into index.html, which reaches the browser as HTML and breaks
        # the dashboard's JSON parsing (see assistant/shared/auth.py). A new user
        # with no uploaded statements is an expected empty-state, not an error —
        # use 422 so the friendly detail passes through CloudFront as JSON.
        raise HTTPException(
            status_code=422,
            detail=(
                f"No bank statements found in your brain for "
                f"period {months[0]} – {months[-1]}. "
                f"Please upload your statement(s) to your brain first."
            ),
        )

    statements_context = "\n\n".join(all_statements)
    if missing_months:
        statements_context += (
            f"\n\nNOTE: No data found for: {', '.join(missing_months)}. "
            f"Exclude these months from the analysis."
        )

    financial_context = await memory_client.fetch_financial_context()
    combined_context = financial_context + ("\n\n" + req.context if req.context else "")

    # Build on the previously saved analysis instead of starting from scratch.
    previous = await memory_client.fetch_latest_analysis("bank-adviser")
    if previous:
        prev_result = dict(previous.get("result") or {})
        prev_result.pop("chart_data", None)  # bulky and re-derived each run
        combined_context = (
            "<previous-analysis>\n"
            f"Your previous analysis (saved {previous.get('saved_at', 'unknown')}, "
            f"months {', '.join(previous.get('months', []))}). Build on it: keep "
            "category assignments consistent, call out month-over-month changes, "
            "and note progress against earlier recommendations.\n"
            f"{json.dumps(prev_result, ensure_ascii=False)}\n"
            "</previous-analysis>\n\n"
        ) + combined_context

    bank_adviser = BankAdviser(
        bedrock_client=bedrock_client,
        model_id=settings.bedrock_model_id,
    )

    user_profile = await build_user_profile(memory_client, domain="banking")

    # Read the user's annual savings goal from their brain.  The goal is stored
    # as a memory containing the marker: ANNUAL_SAVINGS_GOAL=<number> <CURRENCY>
    # (written by the frontend first-run popup).  When absent, yearly_target is
    # None and goal-relative fields are omitted from the analysis rather than
    # computed against a hardcoded default.
    savings_goal = await memory_client.fetch_savings_goal()
    yearly_target: float | None = savings_goal[0] if savings_goal else None
    if savings_goal:
        logger.info(
            "User savings goal: %.2f %s", savings_goal[0], savings_goal[1]
        )
    else:
        logger.info("No savings goal found in brain — goal-relative fields will be omitted")

    try:
        raw = bank_adviser.analyse(
            statement=statements_context,
            context=combined_context,
            user_profile=user_profile,
            yearly_target=yearly_target,
        )
        result = BankAdviserResult.model_validate(raw)
    except Exception as exc:
        logger.exception("BankAdviser analysis failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc

    try:
        await memory_client.save_analysis(
            "bank-adviser",
            {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "mode":     req.mode,
                "months":   months,
                "result":   result.model_dump(),
            },
        )
    except Exception:
        logger.warning("Failed to cache bank-adviser analysis in MCP memory", exc_info=True)

    return result


@app.get("/api/banking/analysis/latest")
async def latest_bank_analysis(settings: SettingsDep, ident: dict = Depends(require_user)):
    """Return the most recently cached bank analysis from MCP memory.

    Lets the dashboard render the last result instantly instead of re-running
    the full fetch + LLM pipeline on every page load.
    """
    memory_client = _make_memory_client(settings, token=ident["token"])
    payload = await memory_client.fetch_latest_analysis("bank-adviser")
    if not payload:
        raise HTTPException(status_code=404, detail="No cached analysis available — run one first.")
    return payload


# ── Investment recommendations ─────────────────────────────────────────────────

@app.post("/api/investing/analyse")
async def analyse_investments(settings: SettingsDep, ident: dict = Depends(require_user)):
    """Analyse the caller's investing position from their uploaded strategy in memory.

    Combines the uploaded strategy, the latest cached bank analysis (savings
    position / investment signal) and the previous investment analysis into a
    current status + allocation recommendation. The result is cached in MCP
    memory and returned as {saved_at, result}.
    """
    memory_client = _make_memory_client(settings, token=ident["token"])

    strategy_context = await memory_client.fetch_investing_strategy()
    bank = await memory_client.fetch_latest_analysis("bank-adviser")
    financial_context = ""
    if bank:
        bank_result = bank.get("result") or {}
        financial_context = json.dumps(
            {
                "saved_at":          bank.get("saved_at"),
                "yearly_progress":   bank_result.get("yearly_progress"),
                "investment_signal": bank_result.get("investment_signal"),
                "budget_next_month": bank_result.get("budget_next_month"),
            },
            ensure_ascii=False,
        )
    previous = await memory_client.fetch_latest_analysis("investing")

    adviser = InvestmentAdviser(
        bedrock_client=_get_bedrock_client(settings.aws_region),
        model_id=settings.bedrock_model_id,
    )
    user_profile = await build_user_profile(memory_client, domain="investing")
    try:
        raw = adviser.analyse(
            strategy_context=strategy_context,
            financial_context=financial_context,
            previous=previous.get("result") if previous else None,
            user_profile=user_profile,
        )
    except Exception as exc:
        logger.exception("Investment analysis failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc

    payload = {"saved_at": datetime.now(timezone.utc).isoformat(), "result": raw}
    try:
        await memory_client.save_analysis("investing", payload)
    except Exception:
        logger.warning("Failed to cache investing analysis in MCP memory", exc_info=True)
    return payload


@app.get("/api/investing/latest")
async def latest_investing_analysis(settings: SettingsDep, ident: dict = Depends(require_user)):
    memory_client = _make_memory_client(settings, token=ident["token"])
    payload = await memory_client.fetch_latest_analysis("investing")
    if not payload:
        raise HTTPException(status_code=404, detail="No cached analysis available — run one first.")
    return payload


# ── Day trading desk ───────────────────────────────────────────────────────────

@app.post("/api/trading/analyse")
async def analyse_day_trading(settings: SettingsDep, ident: dict = Depends(require_user)):
    """Run the daily market analysis (US / Europe / Southeast Asia).

    Fetches a live market snapshot from the web (Yahoo Finance quotes,
    Bloomberg / Economist / Google News headlines), loads the previous
    analysis from MCP memory so the model builds on its own open calls, and
    caches the new result. Returns {saved_at, result, snapshot_meta}.
    """
    memory_client = _make_memory_client(settings, token=ident["token"])

    previous_payload = await memory_client.fetch_latest_analysis("day-trading")
    previous = previous_payload.get("result") if previous_payload else None
    watchlist = [
        rec.get("ticker")
        for rec in (previous or {}).get("recommendations", [])
        if rec.get("ticker")
    ]

    snapshot = await collect_market_snapshot(watchlist)
    strategy_context = await memory_client.fetch_investing_strategy()

    trader = DayTrader(
        bedrock_client=_get_bedrock_client(settings.aws_region),
        model_id=settings.bedrock_model_id,
    )
    user_profile = await build_user_profile(memory_client, domain="trading")
    try:
        raw = trader.analyse(
            market_snapshot=snapshot,
            previous=previous,
            strategy_context=strategy_context,
            user_profile=user_profile,
        )
    except Exception as exc:
        logger.exception("Day trading analysis failed")
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc

    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "result":   raw,
        "snapshot_meta": {
            "fetched_at":     snapshot.get("fetched_at"),
            "sources_ok":     snapshot.get("sources_ok", []),
            "sources_failed": snapshot.get("sources_failed", []),
        },
    }
    try:
        await memory_client.save_analysis("day-trading", payload)
    except Exception:
        logger.warning("Failed to cache day-trading analysis in MCP memory", exc_info=True)
    return payload


@app.get("/api/trading/latest")
async def latest_day_trading_analysis(settings: SettingsDep, ident: dict = Depends(require_user)):
    memory_client = _make_memory_client(settings, token=ident["token"])
    payload = await memory_client.fetch_latest_analysis("day-trading")
    if not payload:
        raise HTTPException(status_code=404, detail="No cached analysis available — run one first.")
    return payload
