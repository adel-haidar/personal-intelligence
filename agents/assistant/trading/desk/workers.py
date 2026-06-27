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
Emit 3-8 directional SIGNALS on liquid, broadly tradeable names, each tied to a
concrete headline or index move in the snapshot (cite it in `evidence`). Spread across
regions when the data supports it. Give a crisp `market_read` (used as the run
headline). If the snapshot is degraded, lower conviction and say so. Respect the
user's universe/asset preferences if provided. You MUST call submit_signals.""".strip()


class Analyst(BaseLLMService):
    def analyse(self, snapshot: dict, profile: str = "", strategy_ctx: str = "") -> dict:
        parts: list[str] = []
        if profile:
            parts.append(profile)
        if strategy_ctx:
            parts.append(f"<strategy-context>\n{strategy_ctx}\n</strategy-context>")
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

TRADEABILITY — every candidate MUST be a real, individually tradeable security:
- ONLY individual stocks or ETFs that exist on a retail broker (e.g. AAPL, MSFT,
  NVDA, ASML, VWCE, SXR8). Use the plain exchange ticker only.
- NEVER propose a market INDEX or an index quote as a trade. The <market-snapshot>
  indices (symbols like ^IXIC, ^GSPC, ^DJI, ^GDAXI, ^STOXX50E, ^FTSE, ^STI, …, or
  anything starting with '^') are CONTEXT ONLY — they show market direction and are
  NOT buyable/sellable. If you want index exposure, use a real ETF ticker instead.
- No ticker may start with '^' or be a currency/commodity index.

SIDES — this desk is funded with NEW cash:
- Default to `buy`. Only use `sell`/`trim` to reduce a position that ACTUALLY appears
  in <current-positions>. If <current-positions> is empty, propose BUYS ONLY — never
  a sell/trim (you cannot sell what you do not hold). Do not invent holdings.

SIZING for SMALL allocations:
- If the allocation is small (e.g. under €100), propose just 1–2 BUYS that each use a
  meaningful chunk of it, so each order is large enough to actually execute at a
  broker (avoid sub-€1 dust orders). Quality over quantity.

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
- No single trade may exceed `max_trade_pct`% of the allocation — trim or reject.
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
