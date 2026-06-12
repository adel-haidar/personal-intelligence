import json
import logging
from datetime import date

from assistant.shared.base_llm_service import BaseLLMService
from assistant.shared.bedrock_retry import invoke_with_tool_retry

logger = logging.getLogger(__name__)


_REGION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "indices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol":     {"type": "string"},
                    "name":       {"type": "string"},
                    "price":      {"type": ["number", "null"]},
                    "change_pct": {"type": ["number", "null"]},
                },
                "required": ["symbol", "name"],
            },
        },
    },
    "required": ["summary", "indices"],
}

_DAY_TRADING_TOOL_SPEC = {
    "name": "submit_day_trading_analysis",
    "description": "Submit the daily market analysis and trading recommendations as structured data.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "analysis_date": {"type": "string"},
                "market_overview": {
                    "type": "object",
                    "properties": {
                        "us":             _REGION_SCHEMA,
                        "europe":         _REGION_SCHEMA,
                        "southeast_asia": _REGION_SCHEMA,
                    },
                    "required": ["us", "europe", "southeast_asia"],
                },
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker":     {"type": "string"},
                            "name":       {"type": "string"},
                            "market":     {"type": "string", "enum": ["us", "europe", "southeast_asia"]},
                            "action":     {"type": "string", "enum": ["buy", "hold", "sell"]},
                            "rationale":  {"type": "string"},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "held_since": {"type": ["string", "null"]},
                        },
                        "required": ["ticker", "name", "market", "action", "rationale", "confidence"],
                    },
                },
                "changes_since_last": {"type": "string"},
                "sources_used":   {"type": "array", "items": {"type": "string"}},
                "risk_note":      {"type": "string"},
                "reasoning":      {"type": "string"},
            },
            "required": [
                "analysis_date", "market_overview", "recommendations",
                "changes_since_last", "sources_used", "risk_note", "reasoning",
            ],
        }
    },
}


_SYSTEM_PROMPT = """You are Adel's day-trading desk analyst embedded in his adel-intelligence system.

SCOPE
- Day-to-day buy/hold/sell calls on individual stocks across THREE regions:
  US, Europe, and Southeast Asia. This desk is separate from his long-term
  investing portfolio.
- Position sizing context: this is a small speculative sleeve of his finances.
  Be decisive but honest about uncertainty.

YOUR INPUTS
1. <market-snapshot> — index quotes and headlines fetched MINUTES AGO from
   Yahoo Finance, Bloomberg, The Economist and Google Finance/News
   (sources_ok / sources_failed list what actually worked; Koyfin has no
   public feed). This snapshot is your ONLY live market data. Never invent
   prices that are not in it.
2. <previous-analysis> — yesterday's (or the last) analysis. BUILD ON IT:
   - Re-evaluate every open recommendation: keep it (hold), close it (sell),
     or add (buy). Carry over held_since dates; set them for new buys.
   - Summarise what changed in changes_since_last.
3. <strategy-context> — optional notes from Adel's memory (Trading 212
   strategy, risk preferences).

GROUND RULES
- Recommendations must reference tickers tradeable on Trading 212 where
  possible (large/mid caps, liquid names).
- 3–8 recommendations total, spread across the three regions when the data
  supports it. Tie each rationale to a concrete headline or index move from
  the snapshot.
- If the snapshot is degraded (sources failed, indices missing), reduce
  conviction and say so in risk_note rather than guessing.
- sources_used: list ONLY the sources that actually contributed (from
  sources_ok).
- risk_note must remind that day trading is high risk and this is not
  professional financial advice.

REASONING
3–8 sentences: snapshot freshness/quality, key market drivers today, how the
previous analysis influenced today's calls.

You will call the submit_day_trading_analysis tool with all fields populated.
""".strip()


class DayTrader(BaseLLMService):
    def analyse(
        self,
        market_snapshot: dict,
        previous: dict | None = None,
        strategy_context: str = "",
    ) -> dict:
        parts: list[str] = []

        if previous:
            parts.append(
                "<previous-analysis>\n"
                f"{json.dumps(previous, ensure_ascii=False)}\n"
                "</previous-analysis>"
            )

        parts.append(
            "<market-snapshot>\n"
            f"{json.dumps(market_snapshot, ensure_ascii=False, indent=1)}\n"
            "</market-snapshot>"
        )

        if strategy_context:
            parts.append(
                "<strategy-context>\n"
                f"{strategy_context}\n"
                "</strategy-context>"
            )

        parts.append(f"Today's date: {date.today().isoformat()}")

        return invoke_with_tool_retry(
            client=self._client,
            model_id=self._model_id,
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [{"text": "\n\n".join(parts)}]}],
            tool_spec=_DAY_TRADING_TOOL_SPEC,
            max_tokens=4096,
            max_retries=2,
        )
