"""Orchestrator for the Agent Trading Desk (orchestrator-workers).

`run_desk(run_id, user_id, config)` drives the full graph and is launched as a
background asyncio task from POST /runs:

    research  (web_scout + Analyst)
      → coordinate
      → strategy (Strategist)
      → evaluate (RiskOfficer)  → write trading_trade rows
      → [Controlled mode] stop at awaiting_approval
        [Auto mode]       continue straight to execute

`execute_run(run_id, user_id)` places kept + non-rejected trades through the chosen
broker adapter (paper sim or live Trading 212), updates trade status / broker order
id / fills and (for paper) positions + cash, then marks the run done.

Every step writes a `trading_run_event` row (work/report/think/spawn/gate/done) so
the frontend stepper can replay the run by polling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from assistant.shared.memory_client import MemoryClient
from assistant.shared.settings import get_settings
from assistant.shared.user_profile import build_user_profile
from assistant.trading import db
from assistant.trading.desk import workers
from assistant.trading.desk.brokers.base import BrokerError
from assistant.trading.desk.brokers.paper import PaperBroker
from assistant.trading.desk.brokers.trading212 import Trading212Broker
from assistant.trading.desk.crypto import decrypt
from assistant.trading.market_data import collect_market_snapshot

logger = logging.getLogger(__name__)

TERMINAL = {"done", "denied", "cancelled", "failed"}


# ── helpers ────────────────────────────────────────────────────────────────────

def _bedrock():
    import boto3
    settings = get_settings()
    return boto3.client("bedrock-runtime", region_name=settings.aws_region)


def _memory_client(token: str | None):
    settings = get_settings()
    if not settings.mcp_memory_url:
        return None
    import boto3
    return MemoryClient(
        bedrock_client=boto3.client("bedrock-runtime", region_name=settings.aws_region),
        model_id=settings.bedrock_model_id,
        server_url=settings.mcp_memory_url,
        token=token,
    )


def _snapshot_price_lookup(snapshot: dict):
    """Build a ticker→price lookup from a market snapshot (indices + watchlist)."""
    prices: dict[str, float] = {}
    for region_quotes in (snapshot.get("indices") or {}).values():
        for q in region_quotes:
            if q.get("symbol") and q.get("price") is not None:
                prices[q["symbol"].upper()] = float(q["price"])
    for q in snapshot.get("watchlist") or []:
        if q.get("symbol") and q.get("price") is not None:
            prices[q["symbol"].upper()] = float(q["price"])

    def lookup(ticker: str):
        return prices.get((ticker or "").upper())

    return lookup


async def _quote_for(ticker: str) -> float | None:
    """Last-resort single-ticker price fetch for paper fills not in the snapshot."""
    try:
        snap = await collect_market_snapshot([ticker])
        for q in snap.get("watchlist") or []:
            if q.get("price") is not None:
                return float(q["price"])
    except Exception:
        logger.warning("Fallback quote fetch failed for %s", ticker, exc_info=True)
    return None


async def _make_broker(user_id, account: str, snapshot: dict | None):
    """Construct the broker adapter for the run's account/funding mode."""
    if account == "paper":
        snap_lookup = _snapshot_price_lookup(snapshot or {})

        async def lookup(ticker: str):
            price = snap_lookup(ticker)
            if price is None:
                price = await _quote_for(ticker)
            return price

        return PaperBroker(user_id, price_lookup=lookup)

    broker = await db.get_broker(user_id, provider="trading212")
    if not broker or not broker.get("api_key_enc"):
        raise BrokerError("No Trading 212 broker connected for live trading.", status=400, code="no_broker")
    api_key = decrypt(broker["api_key_enc"])
    api_secret = decrypt(broker["api_secret_enc"]) if broker.get("api_secret_enc") else None
    return Trading212Broker(api_key, api_secret, environment=broker.get("environment") or "demo")


async def _recompute_notional(run_id, user_id) -> float:
    """Sum the amount of kept, non-rejected trades → run notional."""
    trades = await db.list_trades(run_id, user_id)
    notional = 0.0
    for t in trades:
        if t.get("kept", True) and t.get("risk_verdict") != "rejected" and t.get("status") != "skipped":
            notional += float(t.get("amount") or 0)
    return round(notional, 2)


# ── the run graph ───────────────────────────────────────────────────────────────

async def run_desk(run_id, user_id, config: dict, token: str | None = None) -> None:
    """Background task: research → coordinate → strategy → evaluate → (gate/execute)."""
    account = config.get("account") or "paper"
    mode = config.get("mode") or "controlled"
    try:
        await db.update_run(run_id, status="researching")
        await db.add_event(run_id, user_id, "research", "coordinator", "work",
                           "Starting research — scanning the market.")

        # 1. RESEARCH — web scout + analyst -----------------------------------
        await db.add_event(run_id, user_id, "research", "web_scout", "work",
                           "Fetching live quotes and headlines.")
        snapshot = await collect_market_snapshot()
        await db.add_event(run_id, user_id, "research", "web_scout", "report",
                           f"Snapshot ready ({len(snapshot.get('sources_ok', []))} sources OK).")

        mc = _memory_client(token)
        profile = await build_user_profile(mc, domain="trading") if mc else ""
        strategy_ctx = ""
        if mc:
            try:
                strategy_ctx = await mc.fetch_investing_strategy()
            except Exception:
                logger.warning("fetch_investing_strategy failed", exc_info=True)

        client = _bedrock()
        model_id = get_settings().bedrock_model_id

        await db.add_event(run_id, user_id, "research", "analyst", "think",
                           "Analysing the snapshot for tradeable signals.")
        analyst = workers.Analyst(bedrock_client=client, model_id=model_id)
        signals = await asyncio.to_thread(analyst.analyse, snapshot, profile, strategy_ctx)
        market_read = signals.get("market_read", "")
        await db.update_run(run_id, market_read=market_read)
        await db.add_event(run_id, user_id, "research", "analyst", "report",
                           f"{len(signals.get('signals', []))} signals — {market_read}")

        # 2. COORDINATE -------------------------------------------------------
        await db.add_event(run_id, user_id, "coordinate", "coordinator", "spawn",
                           "Handing signals to the strategist for sizing.")

        # 3. STRATEGY ---------------------------------------------------------
        await db.update_run(run_id, status="drafting")
        positions = []
        try:
            broker = await _make_broker(user_id, account, snapshot)
            positions = await broker.get_positions()
        except Exception:
            logger.warning("Could not load positions for strategist", exc_info=True)
        strategist = workers.Strategist(bedrock_client=client, model_id=model_id)
        drafted = await asyncio.to_thread(strategist.draft, signals, snapshot, config, positions)
        await db.add_event(run_id, user_id, "strategy", "strategist", "report",
                           f"{len(drafted.get('candidates', []))} candidate trades sized.")

        # 4. EVALUATE (risk gate) --------------------------------------------
        await db.update_run(run_id, status="evaluating")
        await db.add_event(run_id, user_id, "evaluate", "risk_officer", "think",
                           "Enforcing guardrails and attaching stop-losses.")
        risk = workers.RiskOfficer(bedrock_client=client, model_id=model_id)
        reviewed = await asyncio.to_thread(risk.evaluate, drafted, config)
        trade_rows = _to_trade_rows(reviewed.get("trades", []), config)
        trade_rows = _sanitize_trades(trade_rows, positions)
        if trade_rows:
            await db.add_trades(run_id, user_id, trade_rows)
        kept = [t for t in trade_rows if t["kept"] and t["risk_verdict"] != "rejected"]
        await db.add_event(run_id, user_id, "evaluate", "risk_officer", "report",
                           f"{len(kept)} trades cleared, {len(trade_rows) - len(kept)} held back.")

        notional = await _recompute_notional(run_id, user_id)
        await db.update_run(run_id, notional=notional)

        # 5. GATE / EXECUTE ---------------------------------------------------
        if mode == "auto":
            await db.add_event(run_id, user_id, "execute", "coordinator", "gate",
                               "Auto mode — executing kept trades.")
            await execute_run(run_id, user_id)
        else:
            await db.update_run(run_id, status="awaiting_approval")
            await db.add_event(run_id, user_id, "execute", "coordinator", "gate",
                               "Awaiting your approval before placing trades.")
    except Exception as exc:
        logger.exception("Trading desk run %s failed", run_id)
        await db.update_run(run_id, status="failed", error=str(exc),
                            finished_at=datetime.now(timezone.utc))
        try:
            await db.add_event(run_id, user_id, "coordinate", "coordinator", "done",
                               f"Run failed: {exc}")
        except Exception:
            pass


def _sanitize_trades(rows: list[dict], positions: list[dict] | None) -> list[dict]:
    """Last-line defence before trades are persisted/placed: reject anything the
    broker can never fill, with a clear reason. Catches the LLM proposing a market
    INDEX (^IXIC, ^GSPC, …) as a trade, or selling/trimming a name the user does
    not actually hold (a fresh cash allocation holds nothing)."""
    held = {(p.get("ticker") or "").strip().upper() for p in (positions or [])}
    for r in rows:
        ticker = (r.get("ticker") or "").strip()
        reason = None
        if not ticker or ticker.upper().startswith("^"):
            reason = f"{ticker or '(empty)'} is a market index, not a tradeable instrument."
        elif r.get("side") in ("sell", "trim") and ticker.upper() not in held:
            reason = f"Cannot {r.get('side')} {ticker} — no existing position in it."
        if reason:
            r["risk_verdict"] = "rejected"
            r["kept"] = False
            r["status"] = "rejected"
            note = (r.get("risk_note") or "").strip()
            r["risk_note"] = (note + " " if note else "") + reason
    return rows


def _to_trade_rows(trades: list[dict], config: dict) -> list[dict]:
    """Normalise RiskOfficer output into trading_trade column dicts."""
    rows: list[dict] = []
    for t in trades:
        verdict = t.get("risk_verdict") or "cleared"
        order_type = t.get("order_type") or "market"
        rows.append({
            "ticker": t.get("ticker"),
            "name": t.get("name") or t.get("ticker"),
            "side": t.get("side") or "buy",
            "amount": float(t.get("amount") or 0),
            "pct_of_allocation": float(t.get("pct_of_allocation") or 0),
            "headline": t.get("headline") or "",
            "reasoning": t.get("reasoning") or "",
            "evidence": t.get("evidence") or [],
            "risk_verdict": verdict,
            "risk_note": t.get("risk_note") or "",
            "order_type": order_type,
            "limit_price": t.get("limit_price"),
            # rejected trades start un-kept so they're not placed by default.
            "kept": verdict != "rejected",
            "status": "rejected" if verdict == "rejected" else "pending",
        })
    return rows


async def execute_run(run_id, user_id) -> None:
    """Place kept + non-rejected trades through the chosen broker adapter."""
    run = await db.get_run(run_id, user_id)
    if run is None:
        raise BrokerError("Run not found.", status=400, code="no_run")
    account = run.get("account") or "paper"

    await db.update_run(run_id, status="executing")
    await db.add_event(run_id, user_id, "execute", "broker", "work",
                       "Placing approved trades.")

    # Fresh snapshot so paper fills use a current price.
    snapshot = await collect_market_snapshot()
    try:
        broker = await _make_broker(user_id, account, snapshot)
    except BrokerError as exc:
        await db.update_run(run_id, status="failed", error=str(exc),
                            finished_at=datetime.now(timezone.utc))
        await db.add_event(run_id, user_id, "execute", "broker", "done", f"Execution failed: {exc}")
        raise

    is_live = account != "paper"
    placed = 0
    for trade in await db.list_trades(run_id, user_id):
        if not trade.get("kept", True) or trade.get("risk_verdict") == "rejected":
            continue
        if trade.get("status") in ("placed", "skipped", "rejected"):
            continue
        try:
            await _place_one(broker, run_id, user_id, trade, is_live)
            placed += 1
        except BrokerError as exc:
            await db.update_trade(trade["id"], user_id, status="rejected")
            await db.add_event(run_id, user_id, "execute", "broker", "report",
                               f"{trade.get('ticker')}: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error placing trade %s", trade.get("id"))
            await db.update_trade(trade["id"], user_id, status="rejected")
            await db.add_event(run_id, user_id, "execute", "broker", "report",
                               f"{trade.get('ticker')}: {exc}")

    await db.update_run(run_id, status="done", finished_at=datetime.now(timezone.utc))
    await db.add_event(run_id, user_id, "execute", "coordinator", "done",
                       f"Run complete — {placed} trade(s) placed.")


async def _place_one(broker, run_id, user_id, trade: dict, is_live: bool) -> None:
    """Resolve symbol, compute quantity, place the order, persist the result."""
    ticker = trade["ticker"]
    resolved = await broker.resolve_symbol(ticker)
    side = trade.get("side") or "buy"
    amount = float(trade.get("amount") or 0)

    # Determine a price to convert cash notional → quantity.
    price = None
    lookup = getattr(broker, "_price_lookup", None)
    if lookup is not None:
        res = lookup(ticker)
        price = await res if hasattr(res, "__await__") else res
    if price is None:
        price = await _quote_for(ticker)
    if not price or price <= 0:
        raise BrokerError(f"No price to size {ticker}.", code="no_price")

    qty = amount / price
    if is_live:
        # Trading 212's API places WHOLE shares only — fractional quantities are
        # rejected ('quantity-precision-mismatch: invalid quantity precision').
        # Floor to an integer count and refuse clearly if the budget can't afford
        # even one share.
        shares = int(abs(qty))
        if shares < 1:
            raise BrokerError(
                f"€{amount:.2f} can't buy one whole share of {ticker} "
                f"(~€{price:.2f}/share). Trading 212 places whole shares only — "
                f"raise the allocation or max-per-trade so one order affords a share.",
                code="below_one_share",
            )
        qty = float(shares)
    qty = -abs(qty) if side in ("sell", "trim") else abs(qty)

    intent_key = f"{run_id}:{trade['id']}"
    # On live, prefer market orders (reliable in beta); honour limit only on paper.
    if trade.get("order_type") == "limit" and trade.get("limit_price") and not is_live:
        order = await broker.place_limit_order(resolved, qty, float(trade["limit_price"]), intent_key=intent_key)
    else:
        order = await broker.place_market_order(resolved, qty, intent_key=intent_key)

    await db.update_trade(
        trade["id"], user_id,
        status="placed",
        broker_order_id=order.get("id"),
        filled_qty=order.get("filled_qty"),
        filled_price=order.get("filled_price"),
    )
    await db.add_event(run_id, user_id, "execute", "broker", "report",
                       f"Placed {side} {ticker} (~{amount:.0f}).")
