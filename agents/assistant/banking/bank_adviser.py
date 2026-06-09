import logging
import re
from datetime import date

from assistant.shared.base_llm_service import BaseLLMService
from assistant.shared.bedrock_retry import invoke_with_tool_retry

logger = logging.getLogger(__name__)

# ── German amount parsing ──────────────────────────────────────────────────────

def parse_german_amount(s: str) -> float:
    s = s.strip().replace("EUR", "").replace("€", "").strip().rstrip("+-")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


_SIGNED_AMOUNT_RE = re.compile(
    r"(?<!\d)([+-])\s*(\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)"
    r"|"
    r"(?<!\d)(\d{1,3}(?:\.\d{3})*,\d{2})\s*([+-])(?!\d)"
)
_SECTION_RE  = re.compile(r"=== BANK STATEMENT (\d{4}-\d{2}) ===")
_OPENING_RE  = re.compile(
    r"(?:Anfangssaldo|Saldo\s*alt|Alter\s*Saldo|Vortrag)\s*[:\s]+"
    r"([+-]?\d{1,3}(?:\.\d{3})*,\d{2})",
    re.IGNORECASE,
)
_CLOSING_RE  = re.compile(
    r"(?:Endsaldo|Saldo\s*neu|Neuer\s*Saldo|Schlusssaldo)\s*[:\s]+"
    r"([+-]?\d{1,3}(?:\.\d{3})*,\d{2})",
    re.IGNORECASE,
)


def _extract_signed_totals(text: str) -> tuple[float, float]:
    credits = 0.0
    debits  = 0.0
    for m in _SIGNED_AMOUNT_RE.finditer(text):
        if m.group(1) is not None:
            sign, raw = m.group(1), m.group(2)
        else:
            raw, sign = m.group(3), m.group(4)
        try:
            amount = parse_german_amount(raw)
        except ValueError:
            continue
        if sign == "+":
            credits += amount
        else:
            debits += amount
    return credits, debits


def _extract_balance_net(text: str) -> float | None:
    opening_m = _OPENING_RE.search(text)
    closing_m = _CLOSING_RE.search(text)
    if not (opening_m and closing_m):
        return None
    try:
        opening = parse_german_amount(opening_m.group(1))
        closing = parse_german_amount(closing_m.group(1))
        return closing - opening
    except ValueError:
        return None


def compute_financial_aggregates(statement_text: str) -> dict:
    """Deterministically compute financial aggregates from raw bank statement text.

    Pure Python — no LLM involved. Splits the multi-month statement on
    '=== BANK STATEMENT YYYY-MM ===' markers, extracts signed amounts via
    regex, and accumulates totals.
    """
    today         = date.today()
    current_year  = today.year
    current_month = today.month
    yearly_target = 10_000.0

    parts = _SECTION_RE.split(statement_text)
    sections: dict[str, str] = {}
    i = 1
    while i + 1 < len(parts):
        sections[parts[i]] = parts[i + 1]
        i += 2
    if not sections:
        sections["unknown"] = statement_text

    period_income   = 0.0
    period_expenses = 0.0
    monthly_nets: dict[str, float] = {}

    for month_str, content in sections.items():
        match_count = len(_SIGNED_AMOUNT_RE.findall(content))
        logger.info(
            "Month %s: %d chars, %d signed-amount regex matches, preview: %r",
            month_str, len(content), match_count, content[:300],
        )
        credits, debits = _extract_signed_totals(content)

        if credits == 0.0 and debits == 0.0:
            balance_net = _extract_balance_net(content)
            if balance_net is not None:
                if balance_net >= 0:
                    credits = balance_net
                else:
                    debits = abs(balance_net)

        monthly_nets[month_str] = credits - debits
        period_income   += credits
        period_expenses += debits

    savings_ytd = sum(
        net for month_str, net in monthly_nets.items()
        if month_str.startswith(str(current_year))
    )

    net_savings_this_period = period_income - period_expenses
    remaining_target        = yearly_target - savings_ytd
    months_elapsed          = current_month
    months_remaining        = 12 - months_elapsed
    pro_rated_target        = yearly_target * months_elapsed / 12
    required_monthly_savings = (
        remaining_target / months_remaining if months_remaining > 0 else 0.0
    )

    if pro_rated_target > 0:
        variance_pct = (savings_ytd - pro_rated_target) / pro_rated_target
        if variance_pct > 0.05:
            trajectory = "ahead"
        elif variance_pct < -0.05:
            trajectory = "behind"
        else:
            trajectory = "on_track"
    else:
        trajectory = "on_track"

    valid = period_income > 0 or period_expenses > 0

    return {
        "valid":                    valid,
        "total_income":             round(period_income, 2),
        "total_expenses":           round(period_expenses, 2),
        "net_savings_this_period":  round(net_savings_this_period, 2),
        "savings_ytd":              round(savings_ytd, 2),
        "yearly_target":            yearly_target,
        "remaining_target":         round(remaining_target, 2),
        "trajectory":               trajectory,
        "required_monthly_savings": round(required_monthly_savings, 2),
        "pro_rated_target":         round(pro_rated_target, 2),
        "months_elapsed":           months_elapsed,
        "months_remaining":         months_remaining,
    }


def validate_financial_json(result: dict, ground_truth: dict) -> dict:
    """Overwrite LLM-computed financial totals with deterministic ground-truth values."""
    if not ground_truth.get("valid", False):
        return result

    def _override(obj: dict, key: str, value: float) -> None:
        if abs(obj.get(key, 0) - value) > 1.0:
            logger.warning(
                "LLM overrode %s (LLM=%s, ground_truth=%s) — correcting",
                key, obj.get(key), value,
            )
        obj[key] = value

    income = result.get("income_summary", {})
    _override(income, "total_income", ground_truth["total_income"])
    result["income_summary"] = income

    spending = result.get("spending_analysis", {})
    _override(spending, "total_expenses",           ground_truth["total_expenses"])
    _override(spending, "net_savings_this_period",  ground_truth["net_savings_this_period"])
    result["spending_analysis"] = spending

    ytd = result.get("yearly_progress", {})
    _override(ytd, "savings_ytd",              ground_truth["savings_ytd"])
    _override(ytd, "remaining_target",         ground_truth["remaining_target"])
    _override(ytd, "required_monthly_savings", ground_truth["required_monthly_savings"])
    _override(ytd, "expected_savings_to_date", ground_truth["pro_rated_target"])
    ytd["trajectory"]       = ground_truth["trajectory"]
    ytd["on_track"]         = ground_truth["trajectory"] != "behind"
    ytd["months_elapsed"]   = ground_truth["months_elapsed"]
    ytd["months_remaining"] = ground_truth["months_remaining"]
    result["yearly_progress"] = ytd

    return result


# ── Tool schema — forces Claude to emit the exact Vue-compatible structure ─────

_ANALYSIS_TOOL_SPEC = {
    "name": "submit_financial_analysis",
    "description": "Submit the complete personal financial analysis as structured data.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "meta": {
                    "type": "object",
                    "properties": {
                        "analysis_date":             {"type": "string"},
                        "analysis_period":           {},
                        "currency":                  {"type": "string"},
                        "data_sources":              {"type": "array", "items": {"type": "string"}},
                        "memory_context_available":  {"type": "boolean"},
                    },
                    "required": ["analysis_date", "analysis_period", "currency"],
                },
                "income_summary": {
                    "type": "object",
                    "properties": {
                        "total_income": {"type": "number"},
                        "sources":      {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["total_income", "sources"],
                },
                "spending_analysis": {
                    "type": "object",
                    "properties": {
                        "total_expenses":          {"type": "number"},
                        "net_savings_this_period": {"type": "number"},
                        "categories":              {"type": "object"},
                        "anomalies":               {"type": "array"},
                        "month_over_month":        {"type": "object"},
                    },
                    "required": [
                        "total_expenses", "net_savings_this_period",
                        "categories", "anomalies", "month_over_month",
                    ],
                },
                "yearly_progress": {
                    "type": "object",
                    "properties": {
                        "target_savings_eur":       {"type": "number"},
                        "savings_ytd":              {"type": "number"},
                        "remaining_target":         {"type": "number"},
                        "months_elapsed":           {"type": "integer"},
                        "months_remaining":         {"type": "integer"},
                        "expected_savings_to_date": {"type": "number"},
                        "variance_from_expected":   {"type": "number"},
                        "required_monthly_savings": {"type": "number"},
                        "trajectory":               {"type": "string", "enum": ["on_track", "ahead", "behind"]},
                        "on_track":                 {"type": "boolean"},
                    },
                    "required": [
                        "target_savings_eur", "savings_ytd", "remaining_target",
                        "required_monthly_savings", "trajectory", "on_track",
                    ],
                },
                "budget_next_month": {
                    "type": "object",
                    "properties": {
                        "proposed_allocations":  {"type": "object"},
                        "projected_net_savings": {"type": "number"},
                    },
                    "required": ["proposed_allocations", "projected_net_savings"],
                },
                "investment_signal": {
                    "type": "object",
                    "properties": {
                        "ready_to_invest":  {"type": "boolean"},
                        "available_amount": {"type": "number"},
                        "note":             {"type": "string"},
                    },
                    "required": ["ready_to_invest", "available_amount", "note"],
                },
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            "category": {"type": "string"},
                            "action":   {"type": "string"},
                        },
                        "required": ["priority", "category", "action"],
                    },
                },
                "savings_opportunities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "current_item":       {"type": "string"},
                            "category":           {"type": "string"},
                            "monthly_cost_eur":   {"type": "number"},
                            "alternative":        {"type": "string"},
                            "monthly_saving_eur": {"type": "number"},
                            "annual_saving_eur":  {"type": "number"},
                            "effort":             {"type": "string"},
                            "prerequisite":       {"type": "string"},
                            "trade_off":          {"type": "string"},
                            "adel_fit_score":     {"type": "string"},
                            "note":               {"type": "string"},
                        },
                        "required": [
                            "current_item", "alternative",
                            "monthly_saving_eur", "annual_saving_eur", "adel_fit_score",
                        ],
                    },
                },
                "chart_data": {
                    "type": "object",
                    "properties": {
                        "spending_by_category_pie": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label":      {"type": "string"},
                                    "value":      {"type": "number"},
                                    "percentage": {"type": "number"},
                                },
                                "required": ["label", "value"],
                            },
                        },
                        "income_vs_expenses_bar": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "month":    {"type": "string"},
                                    "income":   {"type": "number"},
                                    "expenses": {"type": "number"},
                                    "savings":  {"type": "number"},
                                },
                                "required": ["month", "income", "expenses", "savings"],
                            },
                        },
                        "savings_progress_line": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "month":               {"type": "string"},
                                    "cumulative_savings":  {"type": "number"},
                                    "target_line":         {"type": "number"},
                                },
                                "required": ["month", "cumulative_savings", "target_line"],
                            },
                        },
                    },
                    "required": [
                        "spending_by_category_pie",
                        "income_vs_expenses_bar",
                        "savings_progress_line",
                    ],
                },
                "reasoning": {"type": "string"},
            },
            "required": [
                "meta", "income_summary", "spending_analysis", "yearly_progress",
                "budget_next_month", "investment_signal", "recommendations",
                "savings_opportunities", "chart_data", "reasoning",
            ],
        }
    },
}

# ── System prompt — static instructions, no data ──────────────────────────────

_SYSTEM_PROMPT = """You are Adel's personal financial analyst embedded in his adel-intelligence system.

ABOUT ADEL (immutable facts)
- Based in Germany. Salary paid in EUR.
- Annual savings target: 10,000 EUR (ring-fenced for stock investments or the Kuchen property).
- Fixed monthly floor commitments:
    - housing_utilities        ~300 EUR   (electricity, water, heating, internet)
    - insurance                ~300 EUR   (house, dental, liability)
    - family_support            600 EUR   (monthly transfer to parents — non-negotiable)
    - transportation           ~200 EUR   (fuel, public transport, car costs)
    - subscriptions            ~150 EUR   (gym, AWS, Netflix, Spotify, etc.)
    - health_fitness            ~80 EUR   (supplements, gear; gym is in subscriptions)
    - clothing                 ~100 EUR
    - miscellaneous            ~100 EUR
    - professional_development  variable  (AWS SAA-C03 active pipeline; budget dynamically)
    Fixed floor total: ~1,830 EUR/month (excl. professional_development)
- All discretionary spending comes AFTER fixed floor and savings contribution.
- Adel is a gym member and trains regularly — fitness costs are expected.
- He owns an EC2 instance and a Proxmox-capable home machine (Dell OptiPlex, Kuchen) → self-hosting is realistic.
- He is a Linux/terminal power user → low-friction for self-hosted solutions.

MULTI-MONTH FORMAT
Bank statements arrive labelled === BANK STATEMENT YYYY-MM ===.
- chart_data arrays MUST contain one entry PER MONTH.
- meta.analysis_period must be {from: "YYYY-MM-01", to: "YYYY-MM-DD"} using the first and last months.
- yearly_progress.savings_ytd is the SUM of net_savings across all months in the range.
- spending_analysis.categories reflects AGGREGATE spend per category across all months.

ANALYSIS STEPS

STEP 1 — CATEGORISE TRANSACTIONS
Assign every transaction to exactly one category. For ambiguous items prefer the more specific category.

STEP 2 — SPENDING ANALYSIS
- Compute actual spend per category. Compare against budget.
- Status: "ok" (within budget or ≤5% over) | "over" (>5% over) | "under" (>10% under)
- Anomalies:
  • Category >20% over budget → severity "warning"
  • Single transaction >500 EUR outside fixed costs → severity "warning"
  • New recurring charge not in prior context → severity "info"
  • Fixed commitment missing entirely → severity "critical"

STEP 3 — SAVINGS TRACKING
Use PRE-COMPUTED values from the user message for savings_ytd, remaining_target, trajectory,
required_monthly_savings. Do NOT recalculate from transactions.

STEP 4 — NEXT MONTH BUDGET ALLOCATION
Priority: 1) fixed floor 2) savings_contribution to stay on track 3) discretionary.

STEP 5 — INVESTMENT SIGNAL
If savings_ytd ≥ 2,000 EUR above pro-rated target: set ready_to_invest=true.

STEP 6 — RECOMMENDATIONS
3–6 prioritised, concrete actions with EUR amounts.

STEP 7 — SAVINGS OPPORTUNITIES
For every subscription and recurring cost evaluate whether a cheaper/self-hosted alternative exists.
Sort by annual_saving_eur descending. Set adel_fit_score honestly.
Reference: Netflix→Jellyfin/Plex, Spotify→Navidrome, EC2 workloads→home server.

REASONING
Write a plain-text explanation (3–8 sentences) covering: which months had data, how many
transactions you found, whether pre-computed values were used, any data gaps or caveats.
Be specific — mention actual amounts and months.

You will call the submit_financial_analysis tool with all fields populated.
""".strip()


# ── BankAdviser ────────────────────────────────────────────────────────────────

class BankAdviser(BaseLLMService):
    def analyse(self, statement: str, context: str = "") -> dict:
        ground_truth = compute_financial_aggregates(statement)
        if ground_truth["valid"]:
            logger.info(
                "Pre-computed ground truth: income=%.2f expenses=%.2f ytd=%.2f trajectory=%s",
                ground_truth["total_income"],
                ground_truth["total_expenses"],
                ground_truth["savings_ytd"],
                ground_truth["trajectory"],
            )
        else:
            logger.info(
                "Pre-computation found no explicitly-signed amounts; "
                "LLM will derive totals from statement text."
            )

        user_message = self._build_user_message(statement, context, ground_truth)

        result = invoke_with_tool_retry(
            client=self._client,
            model_id=self._model_id,
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            tool_spec=_ANALYSIS_TOOL_SPEC,
            max_tokens=8192,
            max_retries=2,
        )

        return validate_financial_json(result, ground_truth)

    def _build_user_message(
        self,
        statement: str,
        context: str,
        ground_truth: dict,
    ) -> str:
        parts: list[str] = []

        if context:
            parts.append(
                "<memory-context>\n"
                "Context from Adel's personal memory (prior analyses, trading, budgets, goals):\n"
                f"{context}\n"
                "</memory-context>"
            )

        if ground_truth.get("valid"):
            gt = ground_truth
            parts.append(
                "══════════════════════════════════════════\n"
                "PRE-COMPUTED FINANCIAL AGGREGATES — DO NOT RECALCULATE\n"
                "══════════════════════════════════════════\n"
                "Copy these exact values into the corresponding tool fields.\n"
                "Do NOT re-sum or re-derive them from the transaction list.\n\n"
                f"  total_income (this period):      {gt['total_income']:.2f} EUR\n"
                f"  total_expenses (this period):    {gt['total_expenses']:.2f} EUR\n"
                f"  net_savings_this_period:         {gt['net_savings_this_period']:.2f} EUR\n"
                f"  savings_ytd ({date.today().year}):           {gt['savings_ytd']:.2f} EUR\n"
                f"  yearly_target:                   {gt['yearly_target']:.2f} EUR\n"
                f"  remaining_target:                {gt['remaining_target']:.2f} EUR\n"
                f"  trajectory:                      {gt['trajectory']}\n"
                f"  required_monthly_savings:        {gt['required_monthly_savings']:.2f} EUR\n"
                f"  expected_savings_to_date:        {gt['pro_rated_target']:.2f} EUR\n"
                f"  months_elapsed:                  {gt['months_elapsed']}\n"
                f"  months_remaining:                {gt['months_remaining']}\n\n"
                "Your tasks: categorise transactions, compute per-category spend,\n"
                "detect anomalies, propose budget allocations, generate recommendations\n"
                "and savings_opportunities, populate chart_data using the values above."
            )

        parts.append(f"<bank-statement>\n{statement}\n</bank-statement>")

        return "\n\n".join(parts)
