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
from datetime import date, datetime, timedelta, timezone

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

# Trading 212 order-status vocabulary (the subset we act on). A POST returning
# HTTP 200 means "accepted", NOT "filled" — so we resolve the real status before
# recording a trade as placed.
_ORDER_REJECTED = {"REJECTED", "CANCELLED", "DECLINED", "EXPIRED"}
_ORDER_FILLED = {"FILLED", "PARTIALLY_FILLED"}
# Statuses that mean the order genuinely reached the broker's book (done or working).
_ORDER_ON_BOOK = _ORDER_FILLED | {
    "NEW", "CONFIRMED", "SUBMITTED", "WORKING", "LOCAL", "UNCONFIRMED", "REPLACED",
}


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
        trade_rows = _enforce_budget(trade_rows, config)  # code-enforced money guardrails
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


def _enforce_budget(rows: list[dict], config: dict) -> list[dict]:
    """CODE-enforce the money guardrails — never trust the LLM's arithmetic.

    The Strategist/RiskOfficer can emit an `amount` that bears no relation to the
    real allocation (e.g. €1450 on a €25 allocation, mislabelled '5.8%'). This is
    the deterministic backstop: clamp each BUY to max_trade_pct% of the REAL
    allocation, keep the running total within (allocation − reserve), and recompute
    pct_of_allocation from the actual euros. Runs in temperature-0 Python, not an LLM.
    """
    def _f(x, default=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    allocation = _f(config.get("allocation"))
    reserve = _f(config.get("reserve_floor"))
    guardrails = config.get("guardrails") or {}
    max_trade_pct = _f(guardrails.get("max_trade_pct"), 100.0)
    cap_per_trade = allocation * max_trade_pct / 100.0 if allocation else 0.0
    deployable = max(0.0, allocation - reserve)
    spent = 0.0

    for r in rows:
        amount = _f(r.get("amount"))
        if r.get("risk_verdict") == "rejected" or not r.get("kept", True):
            r["pct_of_allocation"] = round(amount / allocation * 100, 2) if allocation else 0
            continue
        if r.get("side") in ("sell", "trim"):
            r["pct_of_allocation"] = round(amount / allocation * 100, 2) if allocation else 0
            continue
        # BUY: clamp to the per-trade cap and the remaining deployable budget.
        capped = min(amount, cap_per_trade) if cap_per_trade else 0.0
        capped = min(capped, max(0.0, deployable - spent))
        if capped <= 0:
            r["risk_verdict"] = "rejected"
            r["kept"] = False
            r["status"] = "rejected"
            note = (r.get("risk_note") or "").strip()
            r["risk_note"] = (note + " " if note else "") + (
                f"No allocation budget left (allocation €{allocation:.0f}, "
                f"max-per-trade {max_trade_pct:.0f}%)."
            )
            r["pct_of_allocation"] = 0
            continue
        if capped < amount - 0.005:
            note = (r.get("risk_note") or "").strip()
            r["risk_note"] = (note + " " if note else "") + (
                f"Sized down to €{capped:.2f} to fit your €{allocation:.0f} allocation "
                f"and {max_trade_pct:.0f}% per-trade cap."
            )
        r["amount"] = round(capped, 2)
        r["pct_of_allocation"] = round(capped / allocation * 100, 2) if allocation else 0
        spent += capped
    return rows


def _to_trade_rows(trades: list[dict], config: dict) -> list[dict]:
    """Normalise RiskOfficer output into trading_trade column dicts."""
    default_stop = (config.get("guardrails") or {}).get("default_stop_pct")
    rows: list[dict] = []
    for t in trades:
        verdict = t.get("risk_verdict") or "cleared"
        order_type = t.get("order_type") or "market"
        side = t.get("side") or "buy"
        # Persist the stop the RiskOfficer attached (default for buys if unset), so
        # execution can place a real protective stop and record it on the position.
        stop_pct = t.get("stop_pct")
        if stop_pct is None and side == "buy":
            stop_pct = default_stop
        rows.append({
            "ticker": t.get("ticker"),
            "name": t.get("name") or t.get("ticker"),
            "side": side,
            "amount": float(t.get("amount") or 0),
            "pct_of_allocation": float(t.get("pct_of_allocation") or 0),
            "headline": t.get("headline") or "",
            "reasoning": t.get("reasoning") or "",
            "evidence": t.get("evidence") or [],
            "risk_verdict": verdict,
            "risk_note": t.get("risk_note") or "",
            "order_type": order_type,
            "limit_price": t.get("limit_price"),
            "stop_pct": float(stop_pct) if stop_pct is not None else None,
            # exit_qty (whole shares) is set for cycle-driven sells/trims; when present
            # execution sells exactly that many shares instead of sizing from a cash amount.
            "exit_qty": t.get("exit_qty"),
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
    # Sells/trims FIRST (they free cash and cancel their protective stop), then buys.
    trades = await db.list_trades(run_id, user_id)
    trades.sort(key=lambda t: 0 if (t.get("side") in ("sell", "trim")) else 1)
    for trade in trades:
        if not trade.get("kept", True) or trade.get("risk_verdict") == "rejected":
            continue
        if trade.get("status") in ("placed", "skipped", "rejected"):
            continue
        try:
            await _place_one(broker, run_id, user_id, account, trade, is_live)
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
                       f"Run complete — {placed} order(s) placed.")


async def _price_for(broker, ticker: str) -> float | None:
    """Best-effort price: broker price-lookup (paper) → fresh Yahoo quote (live)."""
    lookup = getattr(broker, "_price_lookup", None)
    if lookup is not None:
        res = lookup(ticker)
        price = await res if hasattr(res, "__await__") else res
        if price:
            return float(price)
    return await _quote_for(ticker)


async def _place_one(broker, run_id, user_id, account: str, trade: dict, is_live: bool) -> None:
    """Place one order and persist the result + its position plan.

    BUY  → place, confirm, record, attach a protective resting stop, open a plan.
    SELL/TRIM → cancel the protective stop, place, confirm, record, close/shrink plan.
    """
    ticker = trade["ticker"]
    resolved = await broker.resolve_symbol(ticker)
    side = trade.get("side") or "buy"
    amount = float(trade.get("amount") or 0)
    intent_key = f"{run_id}:{trade['id']}"
    is_exit = side in ("sell", "trim")

    # ── size the order ────────────────────────────────────────────────────────
    price = await _price_for(broker, ticker)
    if is_exit:
        # Prefer the exact share count the cycle computed; else size from cash notional.
        exit_qty = trade.get("exit_qty")
        if exit_qty:
            shares = abs(float(exit_qty))
        else:
            if not price or price <= 0:
                raise BrokerError(f"No price to size {ticker}.", code="no_price")
            shares = abs(amount / price)
        if is_live:
            shares = float(int(shares))
        if shares <= 0:
            raise BrokerError(f"Nothing to sell for {ticker}.", code="empty_exit")
        qty = -shares
    else:
        if not price or price <= 0:
            raise BrokerError(f"No price to size {ticker}.", code="no_price")
        qty = amount / price
        if is_live:
            # Trading 212 places WHOLE shares only — floor and refuse if < 1 share.
            shares = int(abs(qty))
            if shares < 1:
                raise BrokerError(
                    f"€{amount:.2f} can't buy one whole share of {ticker} "
                    f"(~€{price:.2f}/share). Trading 212 places whole shares only — "
                    f"raise the allocation or max-per-trade so one order affords a share.",
                    code="below_one_share",
                )
            qty = float(shares)
        qty = abs(qty)

    # ── exits: cancel the resting protective stop BEFORE selling ──────────────
    plan = await db.get_open_plan(user_id, account, ticker) if is_exit else None
    if plan and plan.get("broker_stop_order_id"):
        try:
            await broker.cancel_order(plan["broker_stop_order_id"])
        except BrokerError:
            logger.warning("Could not cancel stop %s for %s", plan["broker_stop_order_id"], ticker)

    # ── place the entry/exit order ────────────────────────────────────────────
    if trade.get("order_type") == "limit" and trade.get("limit_price") and not is_live:
        order = await broker.place_limit_order(resolved, qty, float(trade["limit_price"]), intent_key=intent_key)
    else:
        order = await broker.place_market_order(resolved, qty, intent_key=intent_key)

    # Trust nothing: a 200 means "accepted", not "filled". Resolve the REAL status.
    if is_live:
        order = await _confirm_live_order(broker, order)
    status = (order.get("status") or "").upper()
    if status in _ORDER_REJECTED:
        raise BrokerError(f"Trading 212 {status.lower()} the {ticker} order.", code="order_rejected")
    if is_live and not order.get("id") and status not in _ORDER_ON_BOOK:
        raise BrokerError(
            f"Trading 212 did not confirm the {ticker} order (no order id returned).",
            code="unconfirmed",
        )

    await db.update_trade(
        trade["id"], user_id,
        status="placed",
        broker_order_id=order.get("id"),
        filled_qty=order.get("filled_qty"),
        filled_price=order.get("filled_price"),
    )

    # ── persist the position plan + (for buys) attach a protective stop ───────
    fill_price = order.get("filled_price") or price
    if is_exit:
        sold = abs(qty)
        held = float(plan["qty"]) if plan and plan.get("qty") is not None else None
        if plan and (side == "sell" or (held is not None and sold >= held - 1e-9)):
            realized = None
            if plan.get("entry_price") and fill_price:
                realized = round((float(fill_price) - float(plan["entry_price"])) * sold, 2)
            await db.close_plan(user_id, account, ticker, closed_run_id=run_id, realized_pl=realized)
        elif plan:  # partial trim — shrink the open plan, stop is re-attached next cycle
            remaining = max(0.0, (held or sold) - sold)
            if remaining <= 0:
                await db.close_plan(user_id, account, ticker, closed_run_id=run_id)
            else:
                await db.upsert_open_plan(user_id, account, ticker, qty=remaining)
        verb = "Sold" if side == "sell" else "Trimmed"
    else:
        await _attach_protective_stop(broker, run_id, user_id, account, ticker, resolved,
                                      trade, abs(qty), float(fill_price) if fill_price else None, is_live)
        verb = "Bought"

    if order.get("filled_qty"):
        fill_note = f" — filled {order.get('filled_qty')}"
    elif status and status not in _ORDER_FILLED:
        fill_note = f" — working ({status.lower()})"
    else:
        fill_note = ""
    await db.add_event(run_id, user_id, "execute", "broker", "report",
                       f"{verb} {ticker}{fill_note}.")


async def _attach_protective_stop(broker, run_id, user_id, account, ticker, resolved,
                                  trade, qty: float, entry_price: float | None, is_live: bool) -> None:
    """After a buy, place a resting sell-stop and open/refresh the position plan."""
    stop_pct = trade.get("stop_pct")
    stop_price = None
    broker_stop_order_id = None
    if stop_pct and entry_price:
        stop_price = round(entry_price * (1 - float(stop_pct) / 100.0), 2)
        try:
            stop_order = await broker.place_stop_order(
                resolved, -abs(qty), stop_price, intent_key=f"{run_id}:{trade['id']}:stop"
            )
            broker_stop_order_id = stop_order.get("id")
            await db.add_event(run_id, user_id, "execute", "broker", "report",
                               f"Protective stop for {ticker} @ ~{stop_price:.2f} "
                               f"(−{float(stop_pct):.0f}%).")
        except BrokerError as exc:
            await db.add_event(run_id, user_id, "execute", "broker", "report",
                               f"Could not place protective stop for {ticker}: {exc}")
    await db.upsert_open_plan(
        user_id, account, ticker,
        qty=qty, entry_price=entry_price, stop_price=stop_price,
        thesis=(trade.get("reasoning") or trade.get("headline") or "")[:2000],
        broker_stop_order_id=broker_stop_order_id, opened_run_id=run_id,
    )


async def _confirm_live_order(broker, order: dict) -> dict:
    """Poll the broker for an order's terminal status after submission.

    A freshly-POSTed market order is often NEW/CONFIRMED before it fills. Poll
    get_order() a few times to capture the real outcome (fill price/qty, or a
    rejection) instead of optimistically recording 'placed'. Bounded so the
    background task can't hang: ~5 polls × 1s.
    """
    order_id = order.get("id")
    get_order = getattr(broker, "get_order", None)
    if not order_id or get_order is None:
        return order
    last = order
    for _ in range(5):
        status = (last.get("status") or "").upper()
        if status in _ORDER_REJECTED or status in _ORDER_FILLED:
            return last
        await asyncio.sleep(1.0)
        try:
            last = await get_order(order_id)
        except Exception:
            logger.warning("Could not poll Trading 212 order %s", order_id, exc_info=True)
            return last
    return last


# ── autonomous review cycle (runs every ~30 min during market hours) ────────────

def _f(x, default=None):
    """Coerce Decimal/str/None → float (or default)."""
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _plan_views(plans: list[dict], positions: list[dict]) -> list[dict]:
    """Merge stored exit plans with live position price/qty for the PositionManager."""
    pos_by = {(p.get("ticker") or "").upper(): p for p in positions}
    out = []
    for pl in plans:
        p = pos_by.get((pl.get("ticker") or "").upper(), {})
        out.append({
            "ticker": pl.get("ticker"),
            "entry_price": _f(pl.get("entry_price")),
            "stop_price": _f(pl.get("stop_price")),
            "target_price": _f(pl.get("target_price")),
            "thesis": pl.get("thesis"),
            "qty": _f(p.get("qty"), _f(pl.get("qty"))),
            "current_price": _f(p.get("current_price")),
            "unrealized_pl": _f(p.get("value")),  # T212 maps ppl into 'value'
        })
    return out


async def _reconcile_plans(run_id, user_id, account, positions) -> int:
    """Close any open plan whose ticker is no longer held — it was stopped out (the
    resting T212 stop fired between cycles) or closed elsewhere. This is the
    'stopped out? next cycle reconciles the note' step."""
    held = {(p.get("ticker") or "").upper()
            for p in positions if _f(p.get("qty"), 0) and _f(p.get("qty"), 0) > 0}
    closed = 0
    for pl in await db.list_open_plans(user_id, account):
        if (pl.get("ticker") or "").upper() not in held:
            await db.close_plan(user_id, account, pl["ticker"], closed_run_id=run_id)
            await db.add_event(run_id, user_id, "research", "coordinator", "report",
                               f"{pl['ticker']} no longer held (stop fired or closed) — plan closed.")
            closed += 1
    return closed


def _exit_actions_to_rows(actions: list[dict], plans: list[dict], positions: list[dict]) -> list[dict]:
    """Turn PositionManager sell/trim decisions into ready-to-insert trade rows."""
    plan_by = {(pl.get("ticker") or "").upper(): pl for pl in plans}
    pos_by = {(p.get("ticker") or "").upper(): p for p in positions}
    rows = []
    for a in actions:
        action = (a.get("action") or "hold").lower()
        if action not in ("sell", "trim"):
            continue
        t = (a.get("ticker") or "").upper()
        pl = plan_by.get(t)
        if not pl:
            continue
        held = _f(pos_by.get(t, {}).get("qty"), _f(pl.get("qty"), 0))
        if not held or held <= 0:
            continue
        if action == "sell":
            qty = held
        else:
            frac = _f(a.get("trim_pct"), 50) / 100.0
            qty = min(held, max(1.0, float(int(held * frac))) if held >= 1 else held * frac)
        rows.append({
            "ticker": pl["ticker"], "name": pl.get("ticker"), "side": action,
            "amount": 0.0, "pct_of_allocation": 0.0,
            "headline": f"{action.title()} {pl['ticker']}",
            "reasoning": a.get("reasoning") or "", "evidence": [],
            "risk_verdict": "cleared", "risk_note": a.get("updated_thesis") or "",
            "order_type": "market", "limit_price": None,
            "stop_pct": None, "exit_qty": qty, "kept": True, "status": "pending",
        })
    return rows


async def _apply_holds(run_id, user_id, account, broker, actions, plans, positions, is_live) -> None:
    """For HOLD decisions: refresh the stored thesis and, if the manager tightened the
    stop, cancel+replace the resting stop (never loosen it)."""
    plan_by = {(pl.get("ticker") or "").upper(): pl for pl in plans}
    pos_by = {(p.get("ticker") or "").upper(): p for p in positions}
    for a in actions:
        if (a.get("action") or "hold").lower() != "hold":
            continue
        pl = plan_by.get((a.get("ticker") or "").upper())
        if not pl:
            continue
        updates: dict = {}
        if a.get("updated_thesis"):
            updates["thesis"] = a["updated_thesis"][:2000]
        new_stop_pct = a.get("new_stop_pct")
        if new_stop_pct:
            p = pos_by.get((pl.get("ticker") or "").upper(), {})
            cur = _f(p.get("current_price"), _f(pl.get("entry_price")))
            old_stop = _f(pl.get("stop_price"))
            if cur:
                new_stop = round(cur * (1 - float(new_stop_pct) / 100.0), 2)
                if old_stop is None or new_stop > old_stop:  # only tighten
                    if pl.get("broker_stop_order_id"):
                        try:
                            await broker.cancel_order(pl["broker_stop_order_id"])
                        except BrokerError:
                            logger.warning("Could not cancel stop for %s", pl["ticker"])
                    qty = _f(p.get("qty"), _f(pl.get("qty"), 0))
                    sid = None
                    if qty and qty > 0:
                        try:
                            resolved = await broker.resolve_symbol(pl["ticker"])
                            so = await broker.place_stop_order(
                                resolved, -abs(qty), new_stop, intent_key=f"{run_id}:{pl['ticker']}:trail"
                            )
                            sid = so.get("id")
                        except BrokerError as exc:
                            logger.warning("Could not raise stop for %s: %s", pl["ticker"], exc)
                    updates["stop_price"] = new_stop
                    if sid:
                        updates["broker_stop_order_id"] = sid
                    await db.add_event(run_id, user_id, "evaluate", "position_manager", "report",
                                       f"Raised {pl['ticker']} stop to ~{new_stop:.2f}.")
        if updates:
            await db.upsert_open_plan(user_id, account, pl["ticker"], **updates)


async def _account_equity(account, cash: dict, positions: list[dict]) -> float:
    """Best-effort account equity for the circuit breaker."""
    if account == "live":
        total = cash.get("total")
        if total is not None:
            return _f(total, 0.0)
        return _f(cash.get("free"), 0.0) + _f(cash.get("invested"), 0.0)
    # paper: free cash + market value of positions (paper value = qty*price)
    equity = _f(cash.get("free"), 0.0)
    for p in positions:
        equity += _f(p.get("value"), 0.0)
    return equity


async def _circuit_breaker(user_id, cfg, account, cash, positions, run_id):
    """Daily-loss circuit breaker. Returns (buys_allowed, note). Sets/reads the
    per-day baseline equity and pauses new buys (not exits) for the rest of the day
    once the loss breaches day_loss_pct."""
    today = date.today()
    allocation = _f(cfg.get("allocation"), 0.0)
    day_loss_pct = _f((cfg.get("guardrails") or {}).get("day_loss_pct"), 0.0)
    equity = await _account_equity(account, cash, positions)

    if cfg.get("day_baseline_date") != today:
        # First cycle of the day: anchor the baseline, clear any prior pause.
        await db.set_config_flags(user_id, day_baseline_equity=equity,
                                  day_baseline_date=today, paused_until=None)
        return True, None

    now = datetime.now(timezone.utc)
    paused_until = cfg.get("paused_until")
    if paused_until and now < paused_until:
        return False, "daily-loss circuit breaker active (paused for today)."

    baseline = _f(cfg.get("day_baseline_equity"), equity)
    loss_pct = ((baseline - equity) / allocation * 100.0) if allocation > 0 else 0.0
    if day_loss_pct > 0 and loss_pct >= day_loss_pct:
        eod = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        await db.set_config_flags(user_id, paused_until=eod)
        note = (f"daily loss {loss_pct:.1f}% ≥ {day_loss_pct:.0f}% — circuit breaker tripped; "
                f"no new buys today, protective exits still run.")
        await db.add_event(run_id, user_id, "evaluate", "risk_officer", "gate", note)
        return False, note
    return True, None


async def review_cycle(user_id, token: str | None = None) -> None:
    """One autonomous cycle: reconcile → research → manage exits → (gated) new
    entries → execute. Launched per autonomous user by the 30-min internal job."""
    cfg = await db.get_config(user_id)
    if cfg is None:
        logger.info("No trading config for %s; skipping cycle", user_id)
        return
    account = cfg.get("account") or "paper"

    latest = await db.latest_run(user_id)
    if latest and latest.get("status") in {
        "researching", "drafting", "evaluating", "awaiting_approval", "executing"
    }:
        logger.info("Cycle skipped for %s — a run is already in progress", user_id)
        return

    allocation = _f(cfg.get("allocation"), 0.0)
    reserve = _f(cfg.get("reserve_floor"), 0.0)
    run = await db.create_run(user_id, account=account, strategy=cfg.get("strategy") or "moderate",
                              mode="auto", allocation=allocation, reserve=reserve)
    run_id = run["id"]
    try:
        await db.update_run(run_id, status="researching")
        await db.add_event(run_id, user_id, "research", "coordinator", "work",
                           "Autonomous cycle — reviewing open positions and the market.")
        snapshot = await collect_market_snapshot()
        broker = await _make_broker(user_id, account, snapshot)

        positions, positions_ok = [], False
        try:
            positions = await broker.get_positions()
            positions_ok = True
        except Exception:
            logger.warning("Cycle: could not load positions for %s", user_id, exc_info=True)
        cash = {}
        try:
            cash = await broker.get_cash()
        except Exception:
            logger.warning("Cycle: could not load cash for %s", user_id, exc_info=True)

        # 1. Reconcile plans vs reality (skip if positions unreadable → no false closes).
        if positions_ok:
            await _reconcile_plans(run_id, user_id, account, positions)

        # 2. Research → analyst.
        client = _bedrock()
        model_id = get_settings().bedrock_model_id
        mc = _memory_client(token)
        profile = await build_user_profile(mc, domain="trading") if mc else ""
        strategy_ctx = ""
        if mc:
            try:
                strategy_ctx = await mc.fetch_investing_strategy()
            except Exception:
                logger.warning("fetch_investing_strategy failed", exc_info=True)
        analyst = workers.Analyst(bedrock_client=client, model_id=model_id)
        signals = await asyncio.to_thread(analyst.analyse, snapshot, profile, strategy_ctx)
        market_read = signals.get("market_read", "")
        await db.update_run(run_id, market_read=market_read)
        await db.add_event(run_id, user_id, "research", "analyst", "report",
                           f"{len(signals.get('signals', []))} signals — {market_read}")

        # 3. Exit evaluation over open plans (the "review last run's notes" step).
        await db.update_run(run_id, status="evaluating")
        plans = await db.list_open_plans(user_id, account)
        exit_rows: list[dict] = []
        if plans:
            pm = workers.PositionManager(bedrock_client=client, model_id=model_id)
            decisions = await asyncio.to_thread(pm.review, _plan_views(plans, positions), market_read)
            actions = decisions.get("actions", [])
            exit_rows = _exit_actions_to_rows(actions, plans, positions)
            await _apply_holds(run_id, user_id, account, broker, actions, plans, positions, account != "paper")
            await db.add_event(run_id, user_id, "evaluate", "position_manager", "report",
                               f"{len(exit_rows)} exit(s) from {len(plans)} open position(s).")

        # 4. Circuit breaker.
        buys_allowed, breaker_note = await _circuit_breaker(user_id, cfg, account, cash, positions, run_id)

        # 5. New entries — only NEW names, sized to free cash (skip already-held).
        buy_rows: list[dict] = []
        if buys_allowed:
            free = _f(cash.get("free"), 0.0) or allocation
            entry_cfg = {**cfg, "allocation": min(allocation, free)}
            held = {(p.get("ticker") or "").upper() for p in positions}
            strategist = workers.Strategist(bedrock_client=client, model_id=model_id)
            drafted = await asyncio.to_thread(strategist.draft, signals, snapshot, entry_cfg, positions)
            risk = workers.RiskOfficer(bedrock_client=client, model_id=model_id)
            reviewed = await asyncio.to_thread(risk.evaluate, drafted, entry_cfg)
            rows = _to_trade_rows(reviewed.get("trades", []), entry_cfg)
            rows = [r for r in rows if r["side"] == "buy" and (r.get("ticker") or "").upper() not in held]
            rows = _sanitize_trades(rows, positions)
            buy_rows = _enforce_budget(rows, entry_cfg)
        elif breaker_note:
            await db.add_event(run_id, user_id, "evaluate", "coordinator", "report",
                               "New buys skipped — " + breaker_note)

        # 6. Persist + execute (execute_run does sells first, then buys + stops).
        all_rows = exit_rows + buy_rows
        if all_rows:
            await db.add_trades(run_id, user_id, all_rows)
        await db.update_run(run_id, notional=await _recompute_notional(run_id, user_id))
        await execute_run(run_id, user_id)
    except Exception as exc:
        logger.exception("Autonomous cycle %s failed", run_id)
        await db.update_run(run_id, status="failed", error=str(exc),
                            finished_at=datetime.now(timezone.utc))
        try:
            await db.add_event(run_id, user_id, "execute", "coordinator", "done", f"Cycle failed: {exc}")
        except Exception:
            pass
