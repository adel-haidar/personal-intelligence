"""LLM workers for the Agent Trading Desk (orchestrator-workers pattern).

Three specialists, each a thin BaseLLMService subclass that forces a single
structured tool call via `invoke_with_tool_retry` (which already pins
temperature=0 — appropriate for the deterministic sizing/risk work here):

  - Analyst     — reads the live market snapshot + user profile/strategy and emits
                  directional SIGNALS (which names look interesting and why).
  - Strategist  — turns signals into CANDIDATE TRADES, sized to the allocation,
                  the strategy band, the universe, and the guardrails.
  - RiskOfficer — the gate: enforces guardrails (max_trade_pct, day_loss, reserve
                  floor, crypto cap), sets risk_verdict / risk_note, attaches
                  stop-losses, and may trim or reject.

The trade dict the RiskOfficer returns matches the DB / contract shape:
ticker, name, side, amount, pct_of_allocation, headline, reasoning, evidence,
risk_verdict, risk_note, order_type, limit_price.
"""

import json
import logging
from datetime import date
from decimal import Decimal

from assistant.shared.base_llm_service import BaseLLMService
from assistant.shared.bedrock_retry import invoke_with_tool_retry


def _jsonable(o):
    """json.dumps default: config/positions carry Decimals (from Postgres NUMERIC)
    which are not JSON-serializable on their own."""
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

logger = logging.getLogger(__name__)

# Curated universe of liquid instruments that (1) resolve on Trading 212 and
# (2) have a plain Yahoo Finance symbol so the desk can price them to size orders.
# The snapshot only carries INDICES, so without this the model invents untradeable
# tickers like 'NXUS'. Every entry is US-LISTED (incl. ADRs ASML/SAP/NVO/SHEL): the
# same plain ticker prices on Yahoo (USD) AND resolves on T212. UCITS ETFs are
# intentionally excluded for now — their Yahoo symbols need exchange suffixes
# (VUSA.L) and are quoted in GBp, which broke sizing ("No price to size VUSA").
# The desk picks ONLY from this list, so every candidate is priceable + tradeable.
# `approx_price` is a rough USD per-share level (a HINT for sizing whole-share
# orders within a budget — Trading 212's API places WHOLE shares only, so a BUY
# must afford at least one share). Execution still sizes on the LIVE price; this
# is only so the strategist avoids proposing a €5 buy of a €900 share. Lower-priced
# names are included so small allocations can still buy a whole share of something.
TRADEABLE_UNIVERSE: list[dict] = [
    {"ticker": "F",     "name": "Ford Motor",        "region": "us",     "asset_class": "equity", "approx_price": 12},
    {"ticker": "T",     "name": "AT&T",              "region": "us",     "asset_class": "equity", "approx_price": 23},
    {"ticker": "PFE",   "name": "Pfizer",            "region": "us",     "asset_class": "equity", "approx_price": 26},
    {"ticker": "INTC",  "name": "Intel",             "region": "us",     "asset_class": "equity", "approx_price": 30},
    {"ticker": "BAC",   "name": "Bank of America",   "region": "us",     "asset_class": "equity", "approx_price": 42},
    {"ticker": "CSCO",  "name": "Cisco",             "region": "us",     "asset_class": "equity", "approx_price": 55},
    {"ticker": "SHEL",  "name": "Shell plc",         "region": "europe", "asset_class": "equity", "approx_price": 70},
    {"ticker": "KO",    "name": "Coca-Cola",         "region": "us",     "asset_class": "equity", "approx_price": 70},
    {"ticker": "WMT",   "name": "Walmart",           "region": "us",     "asset_class": "equity", "approx_price": 95},
    {"ticker": "XOM",   "name": "Exxon Mobil",       "region": "us",     "asset_class": "equity", "approx_price": 115},
    {"ticker": "NVO",   "name": "Novo Nordisk",      "region": "europe", "asset_class": "equity", "approx_price": 120},
    {"ticker": "AMD",   "name": "AMD",               "region": "us",     "asset_class": "equity", "approx_price": 160},
    {"ticker": "JNJ",   "name": "Johnson & Johnson", "region": "us",     "asset_class": "equity", "approx_price": 160},
    {"ticker": "PG",    "name": "Procter & Gamble",  "region": "us",     "asset_class": "equity", "approx_price": 165},
    {"ticker": "GOOGL", "name": "Alphabet",          "region": "us",     "asset_class": "equity", "approx_price": 185},
    {"ticker": "AMZN",  "name": "Amazon",            "region": "us",     "asset_class": "equity", "approx_price": 200},
    {"ticker": "JPM",   "name": "JPMorgan Chase",    "region": "us",     "asset_class": "equity", "approx_price": 215},
    {"ticker": "SAP",   "name": "SAP SE",            "region": "europe", "asset_class": "equity", "approx_price": 230},
    {"ticker": "AAPL",  "name": "Apple",             "region": "us",     "asset_class": "equity", "approx_price": 235},
    {"ticker": "NVDA",  "name": "NVIDIA",            "region": "us",     "asset_class": "equity", "approx_price": 135},
    {"ticker": "TSLA",  "name": "Tesla",             "region": "us",     "asset_class": "equity", "approx_price": 250},
    {"ticker": "V",     "name": "Visa",              "region": "us",     "asset_class": "equity", "approx_price": 290},
    {"ticker": "MSFT",  "name": "Microsoft",         "region": "us",     "asset_class": "equity", "approx_price": 450},
    {"ticker": "META",  "name": "Meta Platforms",    "region": "us",     "asset_class": "equity", "approx_price": 580},
    {"ticker": "ASML",  "name": "ASML Holding",      "region": "europe", "asset_class": "equity", "approx_price": 900},
]


def _universe_text() -> str:
    return json.dumps(TRADEABLE_UNIVERSE, ensure_ascii=False)


# ── Analyst ──────────────────────────────────────────────────────────────────

_ANALYST_TOOL = {
    "name": "submit_signals",
    "description": "Submit directional trade signals derived from the market snapshot.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "market_read": {
                    "type": "string",
                    "description": "1-2 sentence read of the market today (used as the run headline).",
                },
                "signals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "name": {"type": "string"},
                            "direction": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                            "conviction": {"type": "string", "enum": ["high", "medium", "low"]},
                            "asset_class": {"type": "string", "enum": ["equity", "crypto", "etf"]},
                            "thesis": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["ticker", "name", "direction", "conviction", "thesis"],
                    },
                },
            },
            "required": ["market_read", "signals"],
        }
    },
}

_ANALYST_SYSTEM = """You are the ANALYST on a multi-agent trading desk.

Read the live <market-snapshot> (quotes + headlines fetched minutes ago — your ONLY
real market data; never invent prices), the user's profile, and any strategy notes.
Emit 3-8 directional SIGNALS, each tied to a concrete headline or index move in the
snapshot (cite it in `evidence`). Give a crisp `market_read` (used as the run
headline). If the snapshot is degraded, lower conviction and say so.

CRITICAL — every signal's `ticker` MUST be chosen from the <tradeable-universe> list
provided in the message (use its exact `ticker`). These are the only instruments the
desk can actually trade. NEVER invent a ticker and NEVER use a market index symbol
(anything starting with '^' such as ^IXIC/^GSPC) — indices are context only, not
tradeable. You MUST call submit_signals.""".strip()


class Analyst(BaseLLMService):
    def analyse(self, snapshot: dict, profile: str = "", strategy_ctx: str = "") -> dict:
        parts: list[str] = []
        if profile:
            parts.append(profile)
        if strategy_ctx:
            parts.append(f"<strategy-context>\n{strategy_ctx}\n</strategy-context>")
        parts.append(f"<tradeable-universe>\n{_universe_text()}\n</tradeable-universe>")
        parts.append(
            "<market-snapshot>\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=1, default=_jsonable)}\n"
            "</market-snapshot>"
        )
        parts.append(f"Today's date: {date.today().isoformat()}")
        return invoke_with_tool_retry(
            client=self._client,
            model_id=self._model_id,
            system_prompt=_ANALYST_SYSTEM,
            messages=[{"role": "user", "content": [{"text": "\n\n".join(parts)}]}],
            tool_spec=_ANALYST_TOOL,
            max_tokens=4096,
            max_retries=2,
        )


# ── Strategist ───────────────────────────────────────────────────────────────

_STRATEGIST_TOOL = {
    "name": "submit_candidates",
    "description": "Submit candidate trades sized to the allocation and guardrails.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "name": {"type": "string"},
                            "side": {"type": "string", "enum": ["buy", "trim", "sell"]},
                            "amount": {
                                "type": "number",
                                "description": "Cash notional in account currency for this order.",
                            },
                            "pct_of_allocation": {
                                "type": "number",
                                "description": "amount as a percentage of the desk allocation (0-100).",
                            },
                            "asset_class": {"type": "string", "enum": ["equity", "crypto", "etf"]},
                            "order_type": {"type": "string", "enum": ["market", "limit"]},
                            "limit_price": {"type": ["number", "null"]},
                            "headline": {"type": "string", "description": "Short card title."},
                            "reasoning": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "ticker", "name", "side", "amount", "pct_of_allocation",
                            "order_type", "headline", "reasoning",
                        ],
                    },
                },
            },
            "required": ["candidates"],
        }
    },
}

_STRATEGIST_SYSTEM = """You are the STRATEGIST on a multi-agent trading desk.

Turn the ANALYST's signals into concrete CANDIDATE TRADES sized in cash. Hard sizing
rules (stated in <desk-config>):
- Total deployed across all BUY candidates must not exceed the ALLOCATION.
- No single trade's `amount` may exceed `max_trade_pct` of the allocation.
- Honour the UNIVERSE: only propose tickers consistent with the allowed universe
  (if a universe list is given, stay within it; otherwise use liquid large/mid caps).
- Crypto exposure (asset_class=crypto) across candidates must not exceed `crypto_pct`
  of the allocation; if crypto_pct is 0, propose no crypto.
- `pct_of_allocation` must equal amount / allocation * 100, rounded sensibly.
- Prefer order_type=market unless a limit is clearly justified (set limit_price then).

TRADEABILITY — this is the most important rule:
- Every candidate's `ticker` MUST be copied EXACTLY from the <tradeable-universe>
  list in the message. That list is the ONLY set of instruments the broker can fill.
- NEVER invent a ticker, and NEVER use a name not in that list (no 'NXUS', no random
  symbols). If you are unsure a name is tradeable, it is not — only the list is.
- NEVER propose a market INDEX. The <market-snapshot> indices (^IXIC, ^GSPC, ^DJI,
  ^GDAXI, ^STOXX50E, ^FTSE, ^STI, … anything starting with '^') are CONTEXT ONLY —
  they show market direction and are NOT tradeable. For index-like exposure use one
  of the ETF tickers in the universe.

SIDES — this desk is funded with NEW cash:
- Default to `buy`. Only use `sell`/`trim` to reduce a position that ACTUALLY appears
  in <current-positions>. If <current-positions> is empty, propose BUYS ONLY — never
  a sell/trim (you cannot sell what you do not hold). Do not invent holdings.

WHOLE-SHARE SIZING (critical — the broker places WHOLE shares only):
- Each <tradeable-universe> entry has an `approx_price` (USD/share). A BUY can only
  execute if its `amount` affords at least ONE whole share, i.e. amount ≳ approx_price.
- For SMALL allocations, pick LOWER-priced names so a whole share fits the per-trade
  budget (e.g. with €25 prefer F/T/PFE/INTC over AAPL/MSFT/ASML). Set each `amount`
  to a whole-share multiple of approx_price (1 share, 2 shares, …), never a fraction
  of a share's price.
- If even the cheapest name's approx_price exceeds the per-trade budget, propose FEWER
  trades (or a single one) concentrated enough to buy one whole share.
- Prefer 1–2 high-conviction BUYS over many dust orders.

Be decisive but conservative; fewer, higher-conviction trades beat many marginal ones.
You MUST call submit_candidates.""".strip()


class Strategist(BaseLLMService):
    def draft(self, signals: dict, snapshot: dict, config: dict, positions: list[dict] | None = None) -> dict:
        guardrails = config.get("guardrails") or {}
        desk_config = {
            "allocation": config.get("allocation"),
            "strategy": config.get("strategy"),
            "reserve_floor": config.get("reserve_floor"),
            "universe": config.get("universe"),
            "max_trade_pct": guardrails.get("max_trade_pct"),
            "crypto_pct": guardrails.get("crypto_pct"),
        }
        parts = [
            f"<desk-config>\n{json.dumps(desk_config, ensure_ascii=False, default=_jsonable)}\n</desk-config>",
            f"<tradeable-universe>\n{_universe_text()}\n</tradeable-universe>",
            f"<signals>\n{json.dumps(signals, ensure_ascii=False, default=_jsonable)}\n</signals>",
            f"<current-positions>\n{json.dumps(positions or [], ensure_ascii=False, default=_jsonable)}\n</current-positions>",
            "<market-snapshot>\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=1, default=_jsonable)}\n"
            "</market-snapshot>",
        ]
        return invoke_with_tool_retry(
            client=self._client,
            model_id=self._model_id,
            system_prompt=_STRATEGIST_SYSTEM,
            messages=[{"role": "user", "content": [{"text": "\n\n".join(parts)}]}],
            tool_spec=_STRATEGIST_TOOL,
            max_tokens=4096,
            max_retries=2,
        )


# ── Risk Officer ─────────────────────────────────────────────────────────────

_RISK_TOOL = {
    "name": "submit_risk_review",
    "description": "Submit the risk-reviewed final trades with verdicts, sizing and stops.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "trades": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "name": {"type": "string"},
                            "side": {"type": "string", "enum": ["buy", "trim", "sell"]},
                            "amount": {"type": "number"},
                            "pct_of_allocation": {"type": "number"},
                            "headline": {"type": "string"},
                            "reasoning": {"type": "string"},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "risk_verdict": {
                                "type": "string",
                                "enum": ["cleared", "adjusted", "protected", "rejected"],
                            },
                            "risk_note": {"type": "string"},
                            "order_type": {"type": "string", "enum": ["market", "limit"]},
                            "limit_price": {"type": ["number", "null"]},
                            "stop_pct": {
                                "type": ["number", "null"],
                                "description": "Suggested stop-loss as a percentage below entry.",
                            },
                        },
                        "required": [
                            "ticker", "name", "side", "amount", "pct_of_allocation",
                            "headline", "reasoning", "risk_verdict", "risk_note",
                            "order_type",
                        ],
                    },
                },
            },
            "required": ["trades"],
        }
    },
}

_RISK_SYSTEM = """You are the RISK OFFICER — the final gate on a multi-agent trading desk.

Review every candidate trade against the GUARDRAILS in <desk-config> and assign a
`risk_verdict`:
- `cleared`   — within all guardrails, no change.
- `adjusted`  — you reduced `amount`/`pct_of_allocation` to fit a guardrail (explain in risk_note).
- `protected` — kept, but you attached/tightened a stop-loss (set `stop_pct`).
- `rejected`  — violates a hard rule and must NOT be placed (e.g. exceeds max_trade_pct
                even after trimming, crypto over the cap, or would breach the reserve floor).

Hard rules:
- A trade whose `pct_of_allocation` is AT OR BELOW `max_trade_pct` is COMPLIANT on
  size — clear it, do not trim or reject it for size. Only when it STRICTLY EXCEEDS
  `max_trade_pct` do you trim it down to the cap (or reject if that's impossible).
  (e.g. with max_trade_pct=10, a trade at exactly 10% is fine.)
- Sum of all non-rejected BUY amounts must keep cash above the `reserve_floor`
  (allocation minus reserve is the deployable ceiling) and respect the day-loss budget.
- Crypto exposure must stay within `crypto_pct`% of allocation.
- Attach a stop-loss (`stop_pct`, default `default_stop_pct`) to every kept BUY and
  mark it `protected` unless already cleared with an equal/tighter stop.
- Recompute `pct_of_allocation` after any amount change.
- REJECT any candidate that is not a real tradeable security: a market index or any
  ticker starting with '^' (e.g. ^IXIC, ^GSPC) is NOT tradeable — verdict `rejected`.
- REJECT any `sell`/`trim` whose ticker is not present in the user's holdings (a
  fresh cash allocation has none) — you cannot sell what is not held.
Be strict and deterministic. Every trade you return MUST have a verdict, a risk_note,
and (for kept buys) a stop. You MUST call submit_risk_review.""".strip()


class RiskOfficer(BaseLLMService):
    def evaluate(self, candidates: dict, config: dict) -> dict:
        guardrails = config.get("guardrails") or {}
        desk_config = {
            "allocation": config.get("allocation"),
            "strategy": config.get("strategy"),
            "reserve_floor": config.get("reserve_floor"),
            "max_trade_pct": guardrails.get("max_trade_pct"),
            "day_loss_pct": guardrails.get("day_loss_pct"),
            "crypto_pct": guardrails.get("crypto_pct"),
            "default_stop_pct": guardrails.get("default_stop_pct"),
        }
        parts = [
            f"<desk-config>\n{json.dumps(desk_config, ensure_ascii=False, default=_jsonable)}\n</desk-config>",
            f"<candidates>\n{json.dumps(candidates, ensure_ascii=False, default=_jsonable)}\n</candidates>",
        ]
        return invoke_with_tool_retry(
            client=self._client,
            model_id=self._model_id,
            system_prompt=_RISK_SYSTEM,
            messages=[{"role": "user", "content": [{"text": "\n\n".join(parts)}]}],
            tool_spec=_RISK_TOOL,
            max_tokens=4096,
            max_retries=2,
        )
