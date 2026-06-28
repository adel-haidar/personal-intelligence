import asyncio
import json
import logging
import httpx
import boto3
import os

from calendar import monthrange
from datetime import date, datetime, time as dt_time, timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from assistant.banking.bank_adviser import BankAdviser
from assistant.banking.investment_adviser import InvestmentAdviser
from assistant.banking.models import BankAdviserResult
from assistant.trading.day_trader import DayTrader
from assistant.trading.market_data import collect_market_snapshot
from assistant.trading import db as trading_db
from assistant.trading.desk import coordinator as desk_coordinator
from assistant.trading.desk.workers import TRADEABLE_UNIVERSE
from assistant.trading.desk.brokers.base import BrokerError
from assistant.trading.desk.brokers.trading212 import Trading212Broker
from assistant.trading.desk.crypto import encrypt
from assistant.health.router import router as health_router
from assistant.job.router import router as job_router
from assistant.shared.auth import require_auth, require_user
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


# ── Agent Trading Desk (orchestrator-workers) ───────────────────────────────────
# All routes under /api/trading/desk. Scoped by ident["user_id"]. Never returns
# secrets, never returns 403 (CloudFront rewrites 403/404 → SPA index.html).

# Strategy → guardrail defaults (from the design handoff / DESK_CONTRACT.md).
_STRATEGY_GUARDRAILS: dict[str, dict] = {
    "conservative": {"max_trade_pct": 8,  "day_loss_pct": 1.5, "crypto_pct": 0,  "default_stop_pct": 6},
    "moderate":     {"max_trade_pct": 18, "day_loss_pct": 4,   "crypto_pct": 10, "default_stop_pct": 6},
    "aggressive":   {"max_trade_pct": 35, "day_loss_pct": 9,   "crypto_pct": 25, "default_stop_pct": 6},
}
_DEFAULT_STRATEGY = "moderate"
_DEFAULT_RESERVE_FLOOR = 5000
_DEFAULT_ALLOCATION = 25000
_NON_TERMINAL = {"researching", "drafting", "evaluating", "awaiting_approval", "executing"}

# Strong references to in-flight desk background tasks. asyncio only keeps WEAK
# references to tasks, so a fire-and-forget create_task() can be garbage-collected
# and silently cancelled mid-run. Hold a ref until the task finishes and log any
# crash so a failed run is never silent.
_DESK_TASKS: set = set()


def _spawn_desk_task(coro) -> None:
    task = asyncio.create_task(coro)
    _DESK_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _DESK_TASKS.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("Trading desk background task crashed", exc_info=t.exception())

    task.add_done_callback(_done)


class DeskConfigUpdate(BaseModel):
    account: Literal["paper", "live"] | None = None
    strategy: Literal["conservative", "moderate", "aggressive"] | None = None
    mode: Literal["controlled", "auto"] | None = None
    allocation: float | None = None
    reserve_floor: float | None = None
    universe: list | dict | None = None
    guardrails: dict | None = None
    autonomous: bool | None = None


# US equity regular hours, resolved in America/New_York so DST is handled. The
# autonomous cycle is gated on this — the universe is US-listed, so trading when
# the market is shut just queues orders (and wastes a Bedrock run).
_NY_TZ = ZoneInfo("America/New_York")


def is_market_open(now: datetime | None = None) -> bool:
    now_ny = (now or datetime.now(timezone.utc)).astimezone(_NY_TZ)
    if now_ny.weekday() >= 5:  # Saturday / Sunday
        return False
    return dt_time(9, 30) <= now_ny.time() <= dt_time(16, 0)


class BrokerUpdate(BaseModel):
    environment: Literal["demo", "live"] = "demo"
    api_key: str
    api_secret: str | None = None
    label: str | None = None


def _seeded_config(user_id, strategy: str = _DEFAULT_STRATEGY) -> dict:
    """Default config (used when a user has none yet)."""
    return {
        "account": "paper",
        "strategy": strategy,
        "mode": "controlled",
        "allocation": _DEFAULT_ALLOCATION,
        "reserve_floor": _DEFAULT_RESERVE_FLOOR,
        "universe": [],
        "guardrails": dict(_STRATEGY_GUARDRAILS[strategy]),
        "autonomous": False,
    }


@app.get("/api/trading/desk/config")
async def desk_get_config(ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    cfg = await trading_db.get_config(user_id)
    if cfg is None:
        cfg = await trading_db.upsert_config(user_id, **_seeded_config(user_id))
    return cfg


@app.put("/api/trading/desk/config")
async def desk_put_config(body: DeskConfigUpdate, ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    current = await trading_db.get_config(user_id) or _seeded_config(user_id)

    fields = body.model_dump(exclude_unset=True)
    # Changing the strategy re-seeds guardrail defaults unless explicitly overridden.
    if "strategy" in fields and "guardrails" not in fields:
        new_strategy = fields["strategy"]
        if new_strategy in _STRATEGY_GUARDRAILS:
            fields["guardrails"] = dict(_STRATEGY_GUARDRAILS[new_strategy])

    merged = {
        "account": fields.get("account", current.get("account", "paper")),
        "strategy": fields.get("strategy", current.get("strategy", _DEFAULT_STRATEGY)),
        "mode": fields.get("mode", current.get("mode", "controlled")),
        "allocation": fields.get("allocation", current.get("allocation", _DEFAULT_ALLOCATION)),
        "reserve_floor": fields.get("reserve_floor", current.get("reserve_floor", _DEFAULT_RESERVE_FLOOR)),
        "universe": fields.get("universe", current.get("universe", [])),
        "guardrails": fields.get("guardrails", current.get("guardrails", dict(_STRATEGY_GUARDRAILS[_DEFAULT_STRATEGY]))),
        "autonomous": fields.get("autonomous", current.get("autonomous", False)),
    }
    return await trading_db.upsert_config(user_id, **merged)


def _broker_view(broker: dict | None) -> dict:
    """Public broker shape — NEVER includes secrets."""
    if not broker:
        return {"connected": False, "provider": "trading212", "environment": None,
                "label": None, "status": None, "last_verified_at": None}
    return {
        "connected": True,
        "provider": broker.get("provider", "trading212"),
        "environment": broker.get("environment"),
        "label": broker.get("label"),
        "status": broker.get("status"),
        "last_verified_at": broker.get("last_verified_at"),
    }


@app.get("/api/trading/desk/broker")
async def desk_get_broker(ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    broker = await trading_db.get_broker(user_id, provider="trading212")
    view = _broker_view(broker)
    # When connected, surface the REAL available cash so the dashboard can bound
    # the allocation to what the account actually holds (best-effort).
    if view["connected"]:
        view["available_cash"] = None
        view["currency"] = None
        try:
            adapter = await desk_coordinator._make_broker(user_id, "live", None)
            cash = await adapter.get_cash()
            view["available_cash"] = cash.get("free")
            view["currency"] = cash.get("currency")
        except Exception:
            logger.warning("Could not read Trading 212 balance", exc_info=True)
    return view


@app.put("/api/trading/desk/broker")
async def desk_put_broker(body: BrokerUpdate, ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    # Verify the key with a real get_cash() call BEFORE storing anything.
    try:
        adapter = Trading212Broker(body.api_key, body.api_secret, environment=body.environment)
        await adapter.get_cash()
    except BrokerError as exc:
        # Bad/unauthorised key → 400 (never 403).
        raise HTTPException(status_code=400, detail=f"Could not verify Trading 212 key: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not verify Trading 212 key: {exc}")

    api_key_enc = encrypt(body.api_key)
    api_secret_enc = encrypt(body.api_secret) if body.api_secret else None
    await trading_db.upsert_broker(
        user_id, "trading212", body.environment, api_key_enc, api_secret_enc,
        "connected", body.label,
    )
    await trading_db.set_broker_verified(user_id, provider="trading212")
    broker = await trading_db.get_broker(user_id, provider="trading212")
    return _broker_view(broker)


@app.delete("/api/trading/desk/broker")
async def desk_delete_broker(ident: dict = Depends(require_user)):
    await trading_db.delete_broker(ident["user_id"], provider="trading212")
    return {"connected": False}


async def _run_bundle(run_id, user_id) -> dict:
    run = await trading_db.get_run(run_id, user_id)
    if run is None:
        raise HTTPException(status_code=400, detail="Run not found.")
    events = await trading_db.list_events(run_id, user_id)
    trades = await trading_db.list_trades(run_id, user_id)
    return {"run": run, "events": events, "trades": trades}


@app.post("/api/trading/desk/runs")
async def desk_start_run(ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    # 409 if a run is already in progress for this user.
    latest = await trading_db.latest_run(user_id)
    if latest and latest.get("status") in _NON_TERMINAL:
        raise HTTPException(status_code=409, detail="A trading run is already in progress.")

    cfg = await trading_db.get_config(user_id)
    if cfg is None:
        cfg = await trading_db.upsert_config(user_id, **_seeded_config(user_id))

    account = cfg.get("account", "paper")
    allocation = float(cfg.get("allocation") or 0)
    reserve = float(cfg.get("reserve_floor") or 0)

    # Live runs: never let the agents deploy more than the account actually holds.
    # Clamp the allocation to (available Trading 212 cash − reserve floor).
    if account == "live":
        # A live run means REAL money. Refuse to run if the connected Trading 212
        # key is a demo/practice key — otherwise orders POST to demo.trading212.com,
        # report "Placed", and never appear in the user's real account.
        broker_row = await trading_db.get_broker(user_id, provider="trading212")
        if not broker_row or not broker_row.get("api_key_enc"):
            raise HTTPException(
                status_code=400,
                detail="Connect your Trading 212 account before running in Live mode.",
            )
        if (broker_row.get("environment") or "demo") != "live":
            raise HTTPException(
                status_code=400,
                detail=("Live mode needs a Live Trading 212 key, but the connected key is "
                        "for the Demo (practice) account. Orders placed with a demo key go "
                        "to your practice account and never reach your real one. Reconnect "
                        "with a Live key, or switch the desk to Paper."),
            )
        try:
            adapter = await desk_coordinator._make_broker(user_id, "live", None)
            cash = await adapter.get_cash()
        except BrokerError as exc:
            raise HTTPException(status_code=400, detail=f"Could not read your Trading 212 balance: {exc}")
        free = float(cash.get("free") or 0)
        max_alloc = max(0.0, free - reserve)
        if allocation > max_alloc:
            allocation = round(max_alloc, 2)
            cfg = {**cfg, "allocation": allocation}
        if allocation <= 0:
            raise HTTPException(
                status_code=400,
                detail=(f"Your Trading 212 available cash (€{free:.2f}) minus the "
                        f"€{reserve:.2f} reserve floor leaves nothing to allocate."),
            )

        # Pre-flight: Trading 212 places WHOLE shares only, so a single trade must
        # afford at least one share of the cheapest available name. Fail fast with
        # guidance instead of running a full pipeline that can place nothing.
        max_trade_pct = float((cfg.get("guardrails") or {}).get("max_trade_pct") or 100)
        per_trade_budget = allocation * max_trade_pct / 100.0
        cheapest = min((u.get("approx_price", 0) for u in TRADEABLE_UNIVERSE), default=0)
        if cheapest and per_trade_budget < cheapest:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Each trade can use at most €{per_trade_budget:.2f} "
                    f"(allocation €{allocation:.0f} × max-per-trade {max_trade_pct:.0f}%), "
                    f"but Trading 212 only buys whole shares and the cheapest available "
                    f"stock is ~€{cheapest:.0f}/share. Raise your allocation or the "
                    f"max-per-trade guardrail so one order can afford a whole share."
                ),
            )

    run = await trading_db.create_run(
        user_id,
        account=account,
        strategy=cfg.get("strategy", _DEFAULT_STRATEGY),
        mode=cfg.get("mode", "controlled"),
        allocation=allocation,
        reserve=reserve,
    )
    # Launch the orchestrator as a detached background task; the frontend polls.
    _spawn_desk_task(desk_coordinator.run_desk(run["id"], user_id, cfg, token=ident["token"]))
    return {"run": run, "events": [], "trades": []}


@app.get("/api/trading/desk/runs/latest")
async def desk_latest_run(ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    run = await trading_db.latest_run(user_id)
    if run is None:
        return {"run": None}
    return await _run_bundle(run["id"], user_id)


@app.get("/api/trading/desk/runs/{run_id}")
async def desk_get_run(run_id: str, ident: dict = Depends(require_user)):
    return await _run_bundle(run_id, ident["user_id"])


@app.post("/api/trading/desk/runs/{run_id}/approve")
async def desk_approve_run(run_id: str, ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    run = await trading_db.get_run(run_id, user_id)
    if run is None:
        raise HTTPException(status_code=400, detail="Run not found.")
    if run.get("status") != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Run is not awaiting approval.")
    # Atomically claim the gate. A concurrent second approval (double-click) loses
    # the race and gets False here, so we never spawn two executors → no duplicate
    # live orders. The DB WHERE clause is the gate, not the check above.
    if not await trading_db.claim_run_for_execution(run_id, user_id):
        # Someone already claimed it (or status moved on) — return current state.
        return await _run_bundle(run_id, user_id)
    _spawn_desk_task(desk_coordinator.execute_run(run_id, user_id))
    return await _run_bundle(run_id, user_id)


@app.post("/api/trading/desk/runs/{run_id}/deny")
async def desk_deny_run(run_id: str, ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    run = await trading_db.get_run(run_id, user_id)
    if run is None:
        raise HTTPException(status_code=400, detail="Run not found.")
    await trading_db.update_run(run_id, status="denied", finished_at=datetime.now(timezone.utc))
    await trading_db.add_event(run_id, user_id, "execute", "coordinator", "done", "Run denied by user.")
    return await _run_bundle(run_id, user_id)


@app.post("/api/trading/desk/runs/{run_id}/cancel")
async def desk_cancel_run(run_id: str, ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    run = await trading_db.get_run(run_id, user_id)
    if run is None:
        raise HTTPException(status_code=400, detail="Run not found.")
    await trading_db.update_run(run_id, status="cancelled", finished_at=datetime.now(timezone.utc))
    await trading_db.add_event(run_id, user_id, "execute", "coordinator", "done", "Run cancelled by user.")
    return await _run_bundle(run_id, user_id)


async def _set_trade_kept_and_return(trade_id: str, user_id, kept: bool) -> dict:
    await trading_db.set_trade_kept(trade_id, user_id, kept)
    trades = None
    # Recompute the owning run's notional.
    trade = None
    # list_trades requires a run_id, so find the trade's run via latest first.
    latest = await trading_db.latest_run(user_id)
    if latest:
        for t in await trading_db.list_trades(latest["id"], user_id):
            if str(t["id"]) == str(trade_id):
                trade = t
                trades = await trading_db.list_trades(latest["id"], user_id)
                break
    if trade is None:
        raise HTTPException(status_code=400, detail="Trade not found.")
    notional = 0.0
    for t in trades or []:
        if t.get("kept", True) and t.get("risk_verdict") != "rejected" and t.get("status") != "skipped":
            notional += float(t.get("amount") or 0)
    await trading_db.update_run(latest["id"], notional=round(notional, 2))
    return trade


@app.post("/api/trading/desk/trades/{trade_id}/keep")
async def desk_keep_trade(trade_id: str, ident: dict = Depends(require_user)):
    return await _set_trade_kept_and_return(trade_id, ident["user_id"], True)


@app.post("/api/trading/desk/trades/{trade_id}/skip")
async def desk_skip_trade(trade_id: str, ident: dict = Depends(require_user)):
    return await _set_trade_kept_and_return(trade_id, ident["user_id"], False)


@app.post("/api/trading/desk/cycle/run")
async def desk_run_cycle(
    user_id: str | None = None,
    force: bool = False,
    _ident: str = Depends(require_auth),  # internal/admin only (INTERNAL_SECRET ok)
):
    """Run the autonomous review cycle. Triggered every 30 min by the systemd timer,
    which fans it over every opted-in user (`list_autonomous_users`). Returns
    immediately; each user's cycle runs as a background task.

    - No `user_id`: fan over all autonomous users, but no-op outside US market hours
      (unless `force=true`).
    - `user_id=<id>`: run ONE user's cycle now (paper testing / manual kick), ignoring
      the market-hours and autonomous-opt-in gates. Internal callers only.

    Memory token is intentionally NOT forwarded per-user here (the internal secret
    resolves to the seed admin in Service A); the cycle trades off the live market +
    guardrails + the user's own open positions, never another tenant's memory.
    """
    if user_id:
        _spawn_desk_task(desk_coordinator.review_cycle(user_id, token=None))
        return {"status": "started", "users": 1, "targeted": True}
    if not force and not is_market_open():
        return {"status": "skipped", "reason": "market_closed"}
    user_ids = await trading_db.list_autonomous_users()
    for uid in user_ids:
        _spawn_desk_task(desk_coordinator.review_cycle(uid, token=None))
    return {"status": "started", "users": len(user_ids)}


def _is_paused(cfg: dict | None) -> bool:
    """True while the daily-loss circuit breaker has new buys paused for the day."""
    pu = (cfg or {}).get("paused_until")
    return bool(pu and datetime.now(timezone.utc) < pu)


def _plan_public(plan: dict) -> dict:
    """Public shape of a managed-position plan (stop/target/thesis) for the UI."""
    def _num(x):
        return float(x) if x is not None else None
    return {
        "ticker": plan.get("ticker"),
        "qty": _num(plan.get("qty")),
        "entry_price": _num(plan.get("entry_price")),
        "stop_price": _num(plan.get("stop_price")),
        "target_price": _num(plan.get("target_price")),
        "thesis": plan.get("thesis"),
        "opened_at": plan.get("opened_at").isoformat() if plan.get("opened_at") else None,
    }


@app.get("/api/trading/desk/portfolio")
async def desk_portfolio(ident: dict = Depends(require_user)):
    user_id = ident["user_id"]
    cfg = await trading_db.get_config(user_id)
    account = (cfg or {}).get("account", "paper")

    if account == "paper":
        acct = await trading_db.get_paper_account(user_id)
        cash = float(acct["cash"])
        starting = float(acct.get("starting_balance", cash))
        positions = await trading_db.get_positions(user_id, "paper")
        snapshot = await collect_market_snapshot()
        price_lookup = desk_coordinator._snapshot_price_lookup(snapshot)
        holdings = []
        holdings_value = 0.0
        for p in positions:
            price = price_lookup(p["ticker"])
            if price is None:
                price = await desk_coordinator._quote_for(p["ticker"])
            qty = float(p["qty"])
            value = round(qty * price, 2) if price else None
            if value:
                holdings_value += value
            holdings.append({
                "ticker": p["ticker"],
                "name": p.get("name") or p["ticker"],
                "value": value,
                "pct": None,
                "day_change": None,
                "asset_class": p.get("asset_class") or "equity",
            })
        total = round(cash + holdings_value, 2)
        for h in holdings:
            if h["value"] and total:
                h["pct"] = round(h["value"] / total * 100, 2)
        plans = await trading_db.list_open_plans(user_id, "paper")
        return {
            "account": "paper",
            "value": total,
            "cash": round(cash, 2),
            "day_change": None,
            "since_funded": round(total - starting, 2),
            "holdings": holdings,
            "autonomous": bool((cfg or {}).get("autonomous")),
            "paused": _is_paused(cfg),
            "managed_positions": [_plan_public(p) for p in plans],
        }

    # Live → Trading 212.
    broker = await trading_db.get_broker(user_id, provider="trading212")
    if not broker or not broker.get("api_key_enc"):
        raise HTTPException(status_code=400, detail="No Trading 212 broker connected.")
    try:
        broker_adapter = await desk_coordinator._make_broker(user_id, "live", None)
        cash = await broker_adapter.get_cash()
        positions = await broker_adapter.get_positions()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=f"Trading 212 unavailable: {exc}")
    holdings = [{
        "ticker": p.get("ticker"),
        "name": p.get("name") or p.get("ticker"),
        "value": p.get("value"),
        "pct": None,
        "day_change": None,
        "asset_class": p.get("asset_class") or "equity",
    } for p in positions]
    free = cash.get("free") or 0
    total = cash.get("total") or free
    plans = await trading_db.list_open_plans(user_id, "live")
    return {
        "account": "live",
        "value": total,
        "cash": free,
        "day_change": None,
        "since_funded": None,
        "holdings": holdings,
        "autonomous": bool((cfg or {}).get("autonomous")),
        "paused": _is_paused(cfg),
        "managed_positions": [_plan_public(p) for p in plans],
    }
