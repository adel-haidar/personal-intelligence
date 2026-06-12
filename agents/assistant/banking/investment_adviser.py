import json
import logging
from datetime import date

from assistant.shared.base_llm_service import BaseLLMService
from assistant.shared.bedrock_retry import invoke_with_tool_retry

logger = logging.getLogger(__name__)


_INVESTMENT_TOOL_SPEC = {
    "name": "submit_investment_analysis",
    "description": "Submit the investment status and allocation recommendation as structured data.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "analysis_date": {"type": "string"},
                "current_status": {
                    "type": "object",
                    "properties": {
                        "strategy_summary":    {"type": "string"},
                        "portfolio_value_eur": {"type": ["number", "null"]},
                        "holdings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name":           {"type": "string"},
                                    "ticker":         {"type": "string"},
                                    "type":           {"type": "string"},
                                    "allocation_pct": {"type": ["number", "null"]},
                                    "value_eur":      {"type": ["number", "null"]},
                                    "note":           {"type": "string"},
                                },
                                "required": ["name"],
                            },
                        },
                        "data_freshness": {"type": "string"},
                    },
                    "required": ["strategy_summary", "holdings", "data_freshness"],
                },
                "allocation_recommendation": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "asset":       {"type": "string"},
                            "ticker":      {"type": "string"},
                            "current_pct": {"type": ["number", "null"]},
                            "target_pct":  {"type": "number"},
                            "action":      {"type": "string", "enum": ["increase", "decrease", "hold", "open", "close"]},
                            "rationale":   {"type": "string"},
                        },
                        "required": ["asset", "target_pct", "action", "rationale"],
                    },
                },
                "monthly_contribution_eur": {"type": ["number", "null"]},
                "notes":     {"type": "array", "items": {"type": "string"}},
                "reasoning": {"type": "string"},
            },
            "required": [
                "analysis_date", "current_status", "allocation_recommendation",
                "notes", "reasoning",
            ],
        }
    },
}


_SYSTEM_PROMPT = """You are Adel's personal investment adviser embedded in his adel-intelligence system.

ABOUT ADEL
- Based in Germany, salary in EUR, invests through Trading 212.
- Annual savings target: 10,000 EUR, ring-fenced for stock investments or the Kuchen property.
- Long-term horizon, but he also runs a separate day-trading desk — this analysis is
  about his INVESTING portfolio (buy-and-hold), not day trades.
- Risk profile: comfortable with equities, prefers low-cost broad ETFs as the core,
  individual stocks as satellites.

YOUR INPUTS
1. <investing-strategy> — Adel's own strategy/portfolio notes uploaded from Trading 212
   (holdings, allocations, pies, watchlists). This is the source of truth for what he
   currently holds. If it is missing or stale, say so in current_status.data_freshness
   and base the status on whatever is available.
2. <financial-context> — his latest bank analysis (savings position, investment signal).
   Use it to judge how much new money is available to invest.
3. <previous-analysis> — your last investment analysis. Build on it: keep terminology
   consistent, highlight what changed, and don't flip-flop recommendations without reason.

YOUR TASKS
1. CURRENT STATUS — summarise the strategy and list holdings with allocations as best
   the data allows. Never invent holdings: if the strategy upload lists none, return an
   empty holdings array and explain in data_freshness.
2. ALLOCATION RECOMMENDATION — propose a target allocation (percentages should sum to
   ~100 across the portfolio) with one entry per asset/position, each with a concrete
   action and rationale grounded in his strategy, savings position, and risk profile.
3. Suggest a monthly_contribution_eur consistent with his savings trajectory (null if
   the financial context is missing).
4. notes — caveats, tax considerations (German Abgeltungssteuer, Freistellungsauftrag),
   data gaps.

REASONING
3–8 sentences: which inputs were available, how fresh they are, what drove the
recommendation, what changed vs the previous analysis.

You will call the submit_investment_analysis tool with all fields populated.
""".strip()


class InvestmentAdviser(BaseLLMService):
    def analyse(
        self,
        strategy_context: str,
        financial_context: str = "",
        previous: dict | None = None,
    ) -> dict:
        parts: list[str] = []

        if previous:
            parts.append(
                "<previous-analysis>\n"
                f"{json.dumps(previous, ensure_ascii=False)}\n"
                "</previous-analysis>"
            )

        parts.append(
            "<investing-strategy>\n"
            f"{strategy_context or 'NO STRATEGY DATA FOUND IN MEMORY.'}\n"
            "</investing-strategy>"
        )

        if financial_context:
            parts.append(
                "<financial-context>\n"
                f"{financial_context}\n"
                "</financial-context>"
            )

        parts.append(f"Today's date: {date.today().isoformat()}")

        return invoke_with_tool_retry(
            client=self._client,
            model_id=self._model_id,
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [{"text": "\n\n".join(parts)}]}],
            tool_spec=_INVESTMENT_TOOL_SPEC,
            max_tokens=4096,
            max_retries=2,
        )
