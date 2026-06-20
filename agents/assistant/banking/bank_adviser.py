import logging
import re
from datetime import date, datetime

from assistant.shared.base_llm_service import BaseLLMService
from assistant.shared.bedrock_retry import invoke_with_tool_retry

logger = logging.getLogger(__name__)

# ── German amount parsing ──────────────────────────────────────────────────────

def parse_german_amount(s: str) -> float:
    s = s.strip().replace("EUR", "").replace("€", "").strip().rstrip("+-")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


# Sparkasse PDF-text layout: every transaction amount sits ALONE on its own
# line, right-aligned. Debits carry a leading '-'; credits are UNSIGNED
# (there is no '+' anywhere in the statement). Matching standalone amount
# lines therefore captures exactly the booked transactions while excluding
# fee-summary lines ('Paketpreis 1 x 9,90    9,90-'), balance lines
# ('Kontostand am ... 6.443,29') and Rechnungsabschluss lines
# ('Kontostand in EUR am ... 2.144,44 +'), all of which have other text on
# the same line. Optional leading/trailing signs keep other bank formats
# (explicit '+', trailing '-') working.
_TXN_LINE_RE = re.compile(
    r"^[ \t]*([+-])?[ \t]*(\d{1,3}(?:\.\d{3})*,\d{2})[ \t]*([+-])?[ \t]*$",
    re.MULTILINE,
)
_SECTION_RE  = re.compile(r"=== BANK STATEMENT (\d{4}-\d{2}) ===")
# Balance lines: 'Kontostand am 30.01.2026 um 20:05 Uhr      6.443,29' and
# 'Kontostand in EUR am 29.12.2025      2.144,44 +'. The amount is the last
# token on the line; the sign (if any) trails it.
_BALANCE_LINE_RE = re.compile(
    r"Kontostand[^\n]*?am\s+(\d{2}\.\d{2}\.\d{4})[^\n]*?"
    r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*,\d{2})\s*([+-])?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_transaction_totals(text: str) -> tuple[float, float]:
    """Sum standalone-line amounts into (credits, debits). Unsigned = credit."""
    credits = 0.0
    debits  = 0.0
    for m in _TXN_LINE_RE.finditer(text):
        leading, raw, trailing = m.groups()
        sign = leading or trailing or "+"
        try:
            amount = parse_german_amount(raw)
        except ValueError:
            continue
        if sign == "-":
            debits += amount
        else:
            credits += amount
    return credits, debits


def _extract_balances(text: str) -> list[tuple[date, float]]:
    """Extract dated 'Kontostand' balance lines, sorted by date.

    A statement's first balance (dated in the previous month) is the opening
    balance; the last is the closing balance. Rechnungsabschluss balances fall
    in between and are harmless once sorted by date.
    """
    entries: list[tuple[date, float]] = []
    for m in _BALANCE_LINE_RE.finditer(text):
        date_str, raw, sign = m.groups()
        try:
            day   = datetime.strptime(date_str, "%d.%m.%Y").date()
            value = parse_german_amount(raw)
        except ValueError:
            continue
        if sign == "-":
            value = -value
        entries.append((day, value))
    entries.sort(key=lambda e: e[0])
    return entries


def _balance_net_for_month(text: str, month_str: str) -> float | None:
    """Net change derived from opening/closing balances, if both are present.

    Only trusted when the earliest balance is dated BEFORE the statement month
    (i.e. it is a genuine opening balance carried over from the prior month) —
    otherwise the earliest line might be a mid-month Rechnungsabschluss.
    """
    entries = _extract_balances(text)
    if len(entries) < 2:
        return None
    try:
        month_start = datetime.strptime(month_str, "%Y-%m").date()
    except ValueError:
        return None
    opening_date, opening = entries[0]
    _, closing = entries[-1]
    if opening_date >= month_start:
        return None
    return closing - opening


def compute_financial_aggregates(
    statement_text: str,
    yearly_target: float | None = None,
) -> dict:
    """Deterministically compute financial aggregates from raw bank statement text.

    Pure Python — no LLM involved. Splits the multi-month statement on
    '=== BANK STATEMENT YYYY-MM ===' markers, sums standalone transaction
    lines (debits signed '-', credits unsigned in the Sparkasse layout), and
    cross-validates each month's net against the statement's opening/closing
    'Kontostand' balances. When both are available and disagree, the balance
    delta wins — it is printed by the bank and immune to extraction noise.

    Args:
        statement_text: Raw concatenated statement text.
        yearly_target: Annual savings goal in the statement's currency, read
            from the user's brain.  When None (goal not set), all
            goal-relative fields (remaining_target, pro_rated_target,
            required_monthly_savings, trajectory) are omitted from the
            returned dict and the LLM is instructed to skip savings-target
            math rather than invent a number.
    """
    today         = date.today()
    current_year  = today.year
    current_month = today.month

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
        credits, debits = _extract_transaction_totals(content)
        balance_net     = _balance_net_for_month(content, month_str)
        txn_net         = credits - debits

        logger.info(
            "Month %s: %d chars, credits=%.2f debits=%.2f txn_net=%.2f balance_net=%s",
            month_str, len(content), credits, debits, txn_net,
            f"{balance_net:.2f}" if balance_net is not None else "n/a",
        )

        if balance_net is not None:
            if abs(balance_net - txn_net) > 2.0:
                logger.warning(
                    "Month %s: transaction sum (%.2f) disagrees with "
                    "opening/closing balance delta (%.2f) — using balance delta",
                    month_str, txn_net, balance_net,
                )
            net = balance_net
        else:
            net = txn_net

        if credits == 0.0 and debits == 0.0 and balance_net is not None:
            # No parseable transaction lines — attribute the whole net so the
            # period totals still reflect this month.
            if net >= 0:
                credits = net
            else:
                debits = abs(net)

        monthly_nets[month_str] = net
        period_income   += credits
        period_expenses += debits

    savings_ytd = sum(
        net for month_str, net in monthly_nets.items()
        if month_str.startswith(str(current_year))
    )

    net_savings_this_period = sum(monthly_nets.values())
    months_elapsed          = current_month
    months_remaining        = 12 - months_elapsed

    valid = period_income > 0 or period_expenses > 0

    result: dict = {
        "valid":                   valid,
        "total_income":            round(period_income, 2),
        "total_expenses":          round(period_expenses, 2),
        "net_savings_this_period": round(net_savings_this_period, 2),
        "monthly_nets":            {m: round(n, 2) for m, n in sorted(monthly_nets.items())},
        "savings_ytd":             round(savings_ytd, 2),
        "yearly_target":           yearly_target,   # None when goal not set
        "months_elapsed":          months_elapsed,
        "months_remaining":        months_remaining,
    }

    if yearly_target is not None:
        remaining_target         = yearly_target - savings_ytd
        pro_rated_target         = yearly_target * months_elapsed / 12
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

        result["remaining_target"]         = round(remaining_target, 2)
        result["pro_rated_target"]         = round(pro_rated_target, 2)
        result["required_monthly_savings"] = round(required_monthly_savings, 2)
        result["trajectory"]               = trajectory

    return result


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
    _override(ytd, "savings_ytd", ground_truth["savings_ytd"])
    ytd["months_elapsed"]   = ground_truth["months_elapsed"]
    ytd["months_remaining"] = ground_truth["months_remaining"]
    # Goal-relative fields are only present when the user has set a savings goal.
    if ground_truth.get("yearly_target") is not None:
        _override(ytd, "remaining_target",         ground_truth["remaining_target"])
        _override(ytd, "required_monthly_savings", ground_truth["required_monthly_savings"])
        _override(ytd, "expected_savings_to_date", ground_truth["pro_rated_target"])
        ytd["trajectory"] = ground_truth["trajectory"]
        ytd["on_track"]   = ground_truth["trajectory"] != "behind"
    else:
        # No goal set: strip any goal-relative values the LLM may have invented.
        for key in ("remaining_target", "required_monthly_savings",
                    "expected_savings_to_date", "trajectory", "on_track"):
            ytd.pop(key, None)
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
                        "categories": {
                            "type": "object",
                            "description": (
                                "Map of category name → breakdown. Field names are "
                                "FIXED: budget, actual, delta, status."
                            ),
                            "additionalProperties": {
                                "type": "object",
                                "properties": {
                                    "budget": {"type": ["number", "null"]},
                                    "actual": {"type": "number"},
                                    "delta":  {"type": ["number", "null"]},
                                    "status": {"type": "string", "enum": ["ok", "over", "under", "tracked"]},
                                    "items": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name":      {"type": "string"},
                                                "amount":    {"type": "number"},
                                                "recurring": {"type": "boolean"},
                                            },
                                            "required": ["name", "amount"],
                                        },
                                    },
                                },
                                "required": ["budget", "actual", "delta", "status"],
                            },
                        },
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
                        "target_savings_eur":       {"type": ["number", "null"]},
                        "savings_ytd":              {"type": "number"},
                        "remaining_target":         {"type": ["number", "null"]},
                        "months_elapsed":           {"type": "integer"},
                        "months_remaining":         {"type": "integer"},
                        "expected_savings_to_date": {"type": ["number", "null"]},
                        "variance_from_expected":   {"type": ["number", "null"]},
                        "required_monthly_savings": {"type": ["number", "null"]},
                        "trajectory":               {"type": "string", "enum": ["on_track", "ahead", "behind"]},
                        "on_track":                 {"type": "boolean"},
                    },
                    "required": ["savings_ytd"],
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
                            "user_fit_score":     {"type": "string"},
                            "note":               {"type": "string"},
                        },
                        "required": [
                            "current_item", "alternative",
                            "monthly_saving_eur", "annual_saving_eur", "user_fit_score",
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

_SYSTEM_PROMPT = """You are the user's personal financial analyst embedded in their Private Internet system.

WHO THE USER IS
The user's identity, location, currency, income, savings goals, and fixed
commitments are provided per-request in an "ABOUT THE USER" block in the user
message (sourced from the user's own brain). Treat that block as the authoritative
source of who the user is. Do NOT assume any country, currency, salary, savings
target, or recurring commitments that are not stated there or evident from the
statement itself. If a needed fact (e.g. a savings target) is unknown, say so
rather than inventing one.

CURRENCY
Use the currency present in the bank statement (EUR, JPY, USD, CHF, GBP, etc.).
Populate meta.currency with the detected currency code (e.g. "JPY", "EUR").
All numeric amounts in the output must be in the statement's native currency —
do NOT convert. Tool fields named "monthly_cost_eur" / "monthly_saving_eur" /
"annual_saving_eur" are kept for schema compatibility; populate them in the
statement's actual currency.

BUDGETING APPROACH
- Derive fixed/recurring commitments from the user's profile and from recurring
  transactions observed in the statements, not from any assumed template.
- All discretionary spending comes AFTER fixed/recurring costs and the savings
  contribution.

MULTI-MONTH FORMAT
Bank statements arrive labelled === BANK STATEMENT YYYY-MM ===.
- Amount sign convention varies by bank and country. Common patterns:
    • German Sparkasse / many European banks: debits carry a leading '-',
      credits (salary, incoming transfers, refunds) are UNSIGNED positive.
    • Japanese banks / some others: explicit '+' for credits, '-' for debits.
    • Some formats use a separate Debit/Credit column.
  Determine the convention from the statement itself and apply it consistently.
- Balance lines (e.g. 'Kontostand am ...', '残高') are account BALANCES, not
  transactions. Fee-annex repeats (e.g. 'Entgeltabschluss', 'Rechnungsabschluss')
  already appear as booked transactions — never count them twice.
- chart_data arrays MUST contain one entry PER MONTH.
- meta.analysis_period must be {from: "YYYY-MM-01", to: "YYYY-MM-DD"} using the first and last months.
- yearly_progress.savings_ytd is the SUM of net_savings across all months in the range.
- spending_analysis.categories reflects AGGREGATE spend per category across all months.

ANALYSIS STEPS

STEP 1 — CATEGORISE TRANSACTIONS
Assign every transaction to exactly one category. For ambiguous items prefer the more specific category.
Transaction descriptions may be in any language (German, Japanese, English, etc.) — translate
or transliterate as needed for category labels in the output.

STEP 2 — SPENDING ANALYSIS
- Compute actual spend per category. Compare against budget.
- spending_analysis.categories entries MUST use exactly these keys:
  {"budget": <monthly budget × months, or null>, "actual": <amount in statement currency>,
   "delta": <budget - actual, or null>, "status": "...", "items": [...]}
  Budgets are MONTHLY floors — multiply by the number of months analysed.
- Status: "ok" (within budget or ≤5% over) | "over" (>5% over) | "under" (>10% under)
- Anomalies:
  • Category >20% over budget → severity "warning"
  • Single large transaction outside fixed costs → severity "warning"
  • New recurring charge not in prior context → severity "info"
  • Fixed commitment missing entirely → severity "critical"

STEP 3 — SAVINGS TRACKING
If PRE-COMPUTED values are provided in the user message, use them directly for
savings_ytd, remaining_target, trajectory, required_monthly_savings.
Do NOT recalculate from transactions when pre-computed values are supplied.
If no pre-computed values are supplied (non-EUR statement or first-time analysis),
derive totals from the statement transactions.

STEP 4 — NEXT MONTH BUDGET ALLOCATION
Priority: 1) fixed floor 2) savings_contribution to stay on track 3) discretionary.

STEP 5 — INVESTMENT SIGNAL
If savings_ytd is meaningfully above the pro-rated yearly target: set ready_to_invest=true.

STEP 6 — RECOMMENDATIONS
3–6 prioritised, concrete actions with amounts in the statement's currency.

STEP 7 — SAVINGS OPPORTUNITIES
For every subscription and recurring cost evaluate whether a cheaper/self-hosted alternative exists.
Sort by annual_saving_eur descending (populate with statement-currency amounts).
Set user_fit_score honestly, judging fit against the user's profile (e.g. their technical
comfort with self-hosting). Reference examples: Netflix→Jellyfin/Plex, Spotify→Navidrome,
cloud workloads→home server.

REASONING
Write a plain-text explanation (3–8 sentences) covering: which months had data, how many
transactions you found, the detected currency and sign convention, whether pre-computed
values were used, any data gaps or caveats. Be specific — mention actual amounts and months.

You will call the submit_financial_analysis tool with all fields populated.
""".strip()


# ── BankAdviser ────────────────────────────────────────────────────────────────

class BankAdviser(BaseLLMService):
    def analyse(
        self,
        statement: str,
        context: str = "",
        user_profile: str = "",
        yearly_target: float | None = None,
    ) -> dict:
        """Run the full financial analysis pipeline.

        Args:
            statement: Concatenated bank statement text (one or more months).
            context: Supplementary memory context from the user's brain.
            user_profile: Plain-text user profile block from build_user_profile.
            yearly_target: Annual savings goal in the statement's native currency,
                read from the user's brain.  Pass None when the user has not yet
                set a goal — goal-relative fields are then omitted from both the
                pre-computed aggregates and the LLM prompt, so the model cannot
                invent a number.
        """
        ground_truth = compute_financial_aggregates(statement, yearly_target=yearly_target)
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
                "Pre-computation found no transaction lines or balances; "
                "LLM will derive totals from statement text."
            )

        user_message = self._build_user_message(statement, context, ground_truth, user_profile, yearly_target)

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
        user_profile: str = "",
        yearly_target: float | None = None,
    ) -> str:
        parts: list[str] = []

        if user_profile:
            parts.append(user_profile)

        if context:
            parts.append(
                "<memory-context>\n"
                "Context from the user's personal memory (prior analyses, trading, budgets, goals):\n"
                f"{context}\n"
                "</memory-context>"
            )

        if ground_truth.get("valid"):
            gt = ground_truth
            monthly_lines = "".join(
                f"    {month}: {net:+.2f}\n"
                for month, net in gt.get("monthly_nets", {}).items()
            )
            has_goal = gt.get("yearly_target") is not None
            goal_lines = (
                f"  yearly_target:                   {gt['yearly_target']:.2f}\n"
                f"  remaining_target:                {gt['remaining_target']:.2f}\n"
                f"  trajectory:                      {gt['trajectory']}\n"
                f"  required_monthly_savings:        {gt['required_monthly_savings']:.2f}\n"
                f"  expected_savings_to_date:        {gt['pro_rated_target']:.2f}\n"
            ) if has_goal else (
                "  yearly_target:                   NOT SET — omit all goal-relative "
                "fields (remaining_target, required_monthly_savings, trajectory, "
                "on_track) from yearly_progress; set target_savings_eur to null.\n"
            )
            parts.append(
                "══════════════════════════════════════════\n"
                "PRE-COMPUTED FINANCIAL AGGREGATES — DO NOT RECALCULATE\n"
                "══════════════════════════════════════════\n"
                "Copy these exact values into the corresponding tool fields.\n"
                "Do NOT re-sum or re-derive them from the transaction list.\n\n"
                f"  net savings per month:\n{monthly_lines}"
                f"  total_income (this period):      {gt['total_income']:.2f}\n"
                f"  total_expenses (this period):    {gt['total_expenses']:.2f}\n"
                f"  net_savings_this_period:         {gt['net_savings_this_period']:.2f}\n"
                f"  savings_ytd ({date.today().year}):           {gt['savings_ytd']:.2f}\n"
                f"{goal_lines}"
                f"  months_elapsed:                  {gt['months_elapsed']}\n"
                f"  months_remaining:                {gt['months_remaining']}\n\n"
                "Your tasks: categorise transactions, compute per-category spend,\n"
                "detect anomalies, propose budget allocations, generate recommendations\n"
                "and savings_opportunities, populate chart_data using the values above.\n"
                "Use 'net savings per month' for income_vs_expenses_bar.savings and the\n"
                "cumulative sums for savings_progress_line.cumulative_savings."
            )

        parts.append(f"<bank-statement>\n{statement}\n</bank-statement>")

        return "\n\n".join(parts)
