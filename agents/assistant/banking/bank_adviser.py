import json
import logging
import re
from datetime import date

from assistant.shared.base_llm_service import BaseLLMService

logger = logging.getLogger(__name__)

# ── German amount parsing ──────────────────────────────────────────────────────

def parse_german_amount(s: str) -> float:
    """Parse a German-format currency string to a float.

    Handles:
        "1.234,56 EUR" → 1234.56
        "-500,00"      → -500.0
        "3.450,00+"    → 3450.0  (sign stripped; caller decides direction)
    """
    s = s.strip().replace("EUR", "").replace("€", "").strip().rstrip("+-")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


# Matches amounts that carry an explicit +/- sign.
# Group layout:
#   (1) sign-before, (2) amount-before  — covers "+1.234,56" and "-500,00"
#   (3) amount-after,  (4) sign-after   — covers "3.450,00+" and "500,00-"
_SIGNED_AMOUNT_RE = re.compile(
    r"(?<!\d)([+-])\s*(\d{1,3}(?:\.\d{3})*,\d{2})(?!\d)"
    r"|"
    r"(?<!\d)(\d{1,3}(?:\.\d{3})*,\d{2})\s*([+-])(?!\d)"
)

# Section headers injected by main.py: "=== BANK STATEMENT 2026-01 ==="
_SECTION_RE = re.compile(r"=== BANK STATEMENT (\d{4}-\d{2}) ===")

# Opening / closing balance keywords (German bank statements)
_OPENING_RE = re.compile(
    r"(?:Anfangssaldo|Saldo\s*alt|Alter\s*Saldo|Vortrag)\s*[:\s]+"
    r"([+-]?\d{1,3}(?:\.\d{3})*,\d{2})",
    re.IGNORECASE,
)
_CLOSING_RE = re.compile(
    r"(?:Endsaldo|Saldo\s*neu|Neuer\s*Saldo|Schlusssaldo)\s*[:\s]+"
    r"([+-]?\d{1,3}(?:\.\d{3})*,\d{2})",
    re.IGNORECASE,
)


def _extract_signed_totals(text: str) -> tuple[float, float]:
    """Return (total_credits, total_debits) from explicitly-signed amounts in text."""
    credits = 0.0
    debits  = 0.0
    for m in _SIGNED_AMOUNT_RE.finditer(text):
        if m.group(1) is not None:       # sign before amount
            sign, raw = m.group(1), m.group(2)
        else:                             # sign after amount
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
    """Try to compute month net from opening/closing balance keywords."""
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

    Splits the concatenated multi-month statement (using the
    '=== BANK STATEMENT YYYY-MM ===' markers) into per-month sections, extracts
    all explicitly-signed amounts with regex, and accumulates totals in pure
    Python — no LLM involved.

    Returns a dict with:
        valid                   – True only when meaningful data was extracted
        total_income            – sum of credited amounts in the analysed period
        total_expenses          – sum of debited amounts (positive value)
        net_savings_this_period – income − expenses for the period
        savings_ytd             – cumulative net across all current-year months
        yearly_target           – hardcoded 10 000 EUR
        remaining_target        – yearly_target − savings_ytd
        trajectory              – "ahead" | "on_track" | "behind"
        required_monthly_savings
        pro_rated_target        – expected YTD savings at current pace
        months_elapsed
        months_remaining
    """
    today          = date.today()
    current_year   = today.year
    current_month  = today.month
    yearly_target  = 10_000.0

    # Split into per-month sections
    parts = _SECTION_RE.split(statement_text)
    # parts = [preamble, month1, text1, month2, text2, …]
    sections: dict[str, str] = {}
    i = 1
    while i + 1 < len(parts):
        sections[parts[i]] = parts[i + 1]
        i += 2

    if not sections:
        # No markers found — treat the whole text as one block
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
            # Fallback: try opening/closing balance difference
            balance_net = _extract_balance_net(content)
            if balance_net is not None:
                if balance_net >= 0:
                    credits = balance_net
                else:
                    debits = abs(balance_net)

        monthly_nets[month_str] = credits - debits
        period_income   += credits
        period_expenses += debits

    # YTD = sum of nets for months in the current calendar year
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

    # Only mark as valid if we extracted non-trivial numbers
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
    """Overwrite LLM-computed financial totals with deterministic ground-truth values.

    Only applied when ground_truth["valid"] is True (i.e. the pre-computation
    layer successfully extracted meaningful numbers from the statement text).
    Logs a warning for every field that diverges by more than €1 from ground truth.
    """
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
    ytd["trajectory"]  = ground_truth["trajectory"]
    ytd["on_track"]    = ground_truth["trajectory"] != "behind"
    ytd["months_elapsed"]   = ground_truth["months_elapsed"]
    ytd["months_remaining"] = ground_truth["months_remaining"]
    result["yearly_progress"] = ytd

    return result


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
                "relying on temperature=0 and prompt constraints for determinism."
            )

        prompt = self.create_financial_assessment(statement, context, ground_truth)
        raw    = self._strip_markdown(self._invoke(prompt, max_tokens=8192, temperature=0.0))
        result = json.loads(raw)
        return validate_financial_json(result, ground_truth)

    def create_financial_assessment(
        self,
        statement: str,
        context: str = "",
        ground_truth: dict | None = None,
    ) -> str:
        context_section = (
            f"\n<memory-context>\n"
            f"Context from Adel's personal memory (prior analyses, trading, budgets, goals):\n"
            f"{context}\n"
            f"</memory-context>\n"
            if context
            else ""
        )

        # Inject pre-computed ground truth when available so the LLM receives
        # authoritative numbers and is not asked to re-derive them.
        if ground_truth and ground_truth.get("valid"):
            gt = ground_truth
            ground_truth_section = f"""
══════════════════════════════════════════
PRE-COMPUTED FINANCIAL AGGREGATES — DO NOT RECALCULATE
══════════════════════════════════════════
These figures were computed deterministically by the application layer from
all available bank statement data. You MUST copy these exact values into the
corresponding JSON fields. Do NOT re-sum, re-derive, or override them from
the transaction list — any discrepancy means an error in your output.

  total_income (this period):      {gt["total_income"]:.2f} EUR
  total_expenses (this period):    {gt["total_expenses"]:.2f} EUR
  net_savings_this_period:         {gt["net_savings_this_period"]:.2f} EUR
  savings_ytd ({date.today().year}):           {gt["savings_ytd"]:.2f} EUR
  yearly_target:                   {gt["yearly_target"]:.2f} EUR
  remaining_target:                {gt["remaining_target"]:.2f} EUR
  trajectory:                      {gt["trajectory"]}
  required_monthly_savings:        {gt["required_monthly_savings"]:.2f} EUR
  expected_savings_to_date:        {gt["pro_rated_target"]:.2f} EUR
  months_elapsed:                  {gt["months_elapsed"]}
  months_remaining:                {gt["months_remaining"]}

Your ONLY tasks for the numeric fields above are to copy them verbatim into
the JSON output. Your actual analytical work is:
  1. Categorise individual transactions into spending categories
  2. Compute per-category actual spend (these ARE your job — only the top-level
     totals above are pre-computed)
  3. Detect anomalies from transaction patterns
  4. Propose next-month budget allocations
  5. Generate savings_opportunities and recommendations
  6. Populate chart_data arrays using the pre-computed totals above
"""
        else:
            ground_truth_section = ""

        prompt = f"""You are Adel's personal financial analyst embedded in his adel-intelligence system.
Your job is to analyse his bank statement and memory context and return a single, valid JSON object — no prose, no markdown fences, no commentary outside the JSON.

══════════════════════════════════════════
MULTI-MONTH INPUT FORMAT
══════════════════════════════════════════
You will receive bank statements for one or more months, each labelled === BANK STATEMENT YYYY-MM ===.

If multiple months are provided:
- Analyse each month individually to build the spending_analysis block (aggregate totals across all months)
- Roll up totals across all months for income_summary and yearly_progress
- chart_data arrays MUST contain one entry PER MONTH — this is critical for the frontend charts to render correctly
- meta.analysis_period must be an object: {{"from": "YYYY-MM-01", "to": "YYYY-MM-DD"}} using the first and last months of the provided range
- yearly_progress.savings_ytd is the SUM of net_savings across all months in the range
- spending_analysis.categories should reflect AGGREGATE spend per category summed across all months

If only one month is provided, behaviour is unchanged.

══════════════════════════════════════════
ABOUT  ME (immutable facts)
══════════════════════════════════════════
- Based in Germany. Salary paid in EUR.
- Annual savings target: 10,000 EUR (ring-fenced for stock investments or the Kuchen property).
- Fixed monthly floor commitments (always respect these first):
    - housing_utilities        →  ~300 EUR   (electricity, water, heating, internet)
    - insurance                →  ~300 EUR   (house, dental, liability)
    - family_support           →   600 EUR   (monthly transfer to parents — non-negotiable)
    - transportation           →  ~200 EUR   (fuel, public transport, car costs)
    - subscriptions            →  ~150 EUR   (gym membership, AWS, Netflix, Spotify, etc. — itemised separately)
    - health_fitness           →  ~80  EUR   (supplements, gear, one-off fitness costs — gym itself is in subscriptions)
    - clothing                 →  ~100 EUR
    - miscellaneous            →  ~100 EUR
    - professional_development →   variable  (AWS SAA-C03 active pipeline; budget dynamically)
    ─────────────────────────────────────
    Fixed floor total        → ~1,830 EUR/month (excl. professional_development)

- All discretionary spending (food, dining, subscriptions, fitness, tech) comes AFTER the floor and savings contribution.
- Adel is a gym member and trains regularly — fitness costs are expected.
{context_section}{ground_truth_section}
══════════════════════════════════════════
ANALYSIS INSTRUCTIONS
══════════════════════════════════════════

STEP 1 — CATEGORISE TRANSACTIONS
  Assign every transaction to exactly one of the categories in the output schema.
  For ambiguous items, prefer the more specific category.
  Professional development: include course platforms (Udemy, A Cloud Guru, Pearson Vue exam fees, etc.).
  Subscriptions: list each service individually in the `items` array.

STEP 2 — SPENDING ANALYSIS
  - Compute actual spend per category.
  - Compare against budget. Set status:
      "ok"       → within budget or ≤5% over
      "over"     → >5% over budget
      "under"    → >10% under budget (flag as potential underspend)
  - Detect anomalies:
      • Any category >20% over its budget  → severity "warning"
      • Any single transaction >500 EUR outside fixed costs → severity "warning"
      • Any new recurring charge not seen in prior context → severity "info"
      • Fixed commitment missing entirely (e.g. no family_support transfer) → severity "critical"

STEP 3 — SAVINGS TRACKING
  - Use the PRE-COMPUTED values above for savings_ytd, remaining_target, trajectory,
    and required_monthly_savings. Do NOT recalculate these from the transaction list.
  - If no pre-computed block is present, derive savings_ytd from memory context
    if available; otherwise use 0 and note data gap.
  - Calculate remaining months in the calendar year from analysis_period.to.
  - Trajectory definitions (for reference only — use pre-computed value if provided):
      "ahead"    → cumulative savings / elapsed months > (10000 / 12)
      "on_track" → within ±5% of expected pace
      "behind"   → >5% below expected pace

STEP 4 — NEXT MONTH BUDGET ALLOCATION
  Priority order:
    1. All fixed floor items (non-negotiable amounts above)
    2. savings_contribution: calculate the exact amount needed to stay/get on track for 10,000 EUR
    3. Discretionary: propose realistic amounts based on this month's actuals, with reductions flagged if necessary
  Include known_upcoming items in professional_development (e.g. scheduled exams, course renewals).
  Leave a note on every category where you deviate from the simple repeat of last month.

STEP 5 — INVESTMENT SIGNAL
  If savings_ytd ≥ 2,000 EUR above the pro-rated annual target, set ready_to_invest: true and propose an available_amount to shift into the investment bucket.
  Keep the investment_note factual — Adel makes the final decision.

STEP 6 — RECOMMENDATIONS
  Produce 3–6 prioritised, concrete recommendations.
  Format: specific action, not vague advice ("Cancel Audible subscription — 9.95 EUR/month, not used this period" not "Review subscriptions").

STEP 7 — SAVINGS OPPORTUNITIES AUDIT
  For every subscription and recurring cost — including non-negotiable items — evaluate whether a cheaper or self-hosted alternative exists.
  Prioritise suggestions that fit Adel's profile:
    • He owns an EC2 instance and has a Proxmox-capable machine at home (Dell OptiPlex) → self-hosting is a realistic option.
    • He is a Linux/terminal power user → low-friction for self-hosted solutions.
    • He has a home in Kuchen with stable internet → home lab is viable.

  Reference examples (always include if applicable):
    • Netflix          → self-host Plex or Jellyfin on the home Proxmox server. Saving: ~13–18 EUR/month.
    • Spotify          → self-host Navidrome or use YouTube Music (cheaper). Saving: ~10 EUR/month.
    • AWS EC2 instance → migrate workloads that don't require public egress to home server. Saving: variable, flag actual EC2 cost from transactions.
    • AWS other        → identify which AWS services appear in transactions; flag any that could move to free tier or home.
    • Gym membership   → only flag if usage signals suggest low attendance (no corroborating food/transport spend on gym days).

  Set adel_fit_score:
    "high"   → realistic given his skills and home infrastructure
    "medium" → feasible but requires new setup or trade-off
    "low"    → technically possible but impractical given his situation

  Always include trade_off honestly — do not recommend blindly.
  Sort by annual_saving_eur descending.

══════════════════════════════════════════
OUTPUT JSON SCHEMA
══════════════════════════════════════════
Return ONLY the following JSON. Fill every field. Use null only where data is genuinely unavailable.

{{
  "meta": {{
    "analysis_date": "<ISO 8601 date of generation>",
    "analysis_period": {{
      "from": "<YYYY-MM-DD>",
      "to":   "<YYYY-MM-DD>"
    }},
    "currency": "EUR",
    "data_sources": ["bank_statement", "mcp_memory"],
    "memory_context_available": true
  }},

  "income_summary": {{
    "total_income": 0.0,
    "sources": [
      {{"label": "<source name e.g. adesso SE salary>", "amount": 0.0, "recurring": true}}
    ]
  }},

  "spending_analysis": {{
    "total_expenses": 0.0,
    "net_savings_this_period": 0.0,

    "categories": {{
      "housing_utilities":       {{"budget": 300.0,  "actual": 0.0, "delta": 0.0, "status": "ok"}},
      "insurance":               {{"budget": 300.0,  "actual": 0.0, "delta": 0.0, "status": "ok"}},
      "family_support":          {{"budget": 600.0,  "actual": 0.0, "delta": 0.0, "status": "ok"}},
      "transportation":          {{"budget": 200.0,  "actual": 0.0, "delta": 0.0, "status": "ok"}},
      "food_groceries":          {{"budget": null,   "actual": 0.0, "delta": null,"status": "tracked"}},
      "dining_restaurants":      {{"budget": null,   "actual": 0.0, "delta": null,"status": "tracked"}},
      "professional_development":{{"budget": null,   "actual": 0.0, "delta": null,"status": "tracked",
                                   "items": [{{"name": "<course/exam>", "amount": 0.0}}]}},
      "clothing":                {{"budget": 100.0,  "actual": 0.0, "delta": 0.0, "status": "ok"}},
      "subscriptions":           {{ "budget": 150.0, "actual": 0.0, "delta":  0.0, "status": "ok",
                                "items":  [{{"name": "<service e.g. Netflix>", "amount": 0.0, "recurring": true}}]
                                 }},
      "health_fitness":          {{ "budget": 80.0, "actual": 0.0, "delta":  0.0, "status": "ok" }},
      "miscellaneous":           {{"budget": 100.0,  "actual": 0.0, "delta": 0.0, "status": "ok"}}
    }},

    "anomalies": [
      {{
        "category":    "<category_key>",
        "description": "<human-readable explanation>",
        "amount":       0.0,
        "severity":    "info | warning | critical"
      }}
    ],

    "month_over_month": {{
      "available": false,
      "note": "<e.g. 'Prior month data loaded from memory' or 'No prior data available'>",
      "changes": [
        {{"category": "<cat>", "previous": 0.0, "current": 0.0, "change_pct": 0.0}}
      ]
    }}
  }},

  "yearly_progress": {{
    "target_savings_eur":        10000.0,
    "savings_ytd":               0.0,
    "remaining_target":          0.0,
    "months_elapsed":            0,
    "months_remaining":          0,
    "expected_savings_to_date":  0.0,
    "variance_from_expected":    0.0,
    "required_monthly_savings":  0.0,
    "trajectory":                "on_track | ahead | behind",
    "on_track":                  true
  }},

  "budget_next_month": {{
    "proposed_allocations": {{
      "housing_utilities":        {{"proposed": 300.0, "note": ""}},
      "insurance":                {{"proposed": 300.0, "note": ""}},
      "family_support":           {{"proposed": 600.0, "note": ""}},
      "transportation":           {{"proposed": 200.0, "note": ""}},
      "food_groceries":           {{"proposed": 0.0,   "note": ""}},
      "dining_restaurants":       {{"proposed": 0.0,   "note": ""}},
      "professional_development": {{"proposed": 0.0,   "note": "", "known_upcoming": [{{"item": "<exam/course>", "est_cost": 0.0, "date": "<YYYY-MM>"}}]}},
      "clothing":                 {{"proposed": 100.0, "note": ""}},
      "subscriptions":            {{"proposed": 150.0, "note": "", "items_review_due": [{{"name": "<service>", "last_used": "<YYYY-MM>", "flag": "active|unused|review"}}] }},
      "health_fitness":           {{"proposed": 80.0, "note": ""}},
      "miscellaneous":            {{"proposed": 100.0, "note": ""}},
      "savings_contribution":     {{"proposed": 0.0,   "note": "Derived from yearly trajectory"}}
    }},
    "total_proposed_expenses":   0.0,
    "projected_net_savings":     0.0
  }},

  "investment_signal": {{
    "ready_to_invest":  false,
    "available_amount": 0.0,
    "note":             "<brief factual note — e.g. 'On pace; 1,200 EUR above target threshold'>"
  }},

  "recommendations": [
    {{
      "priority": "high | medium | low",
      "category": "<category_key>",
      "action":   "<specific, concrete action with EUR amount where applicable>"
    }}
  ],
  "savings_opportunities": [
    {{
      "current_item":         "<what Adel currently pays for>",
      "category":             "<category_key>",
      "monthly_cost_eur":     0.0,
      "alternative":          "<concrete replacement or action>",
      "monthly_saving_eur":   0.0,
      "annual_saving_eur":    0.0,
      "effort":               "low | medium | high",
      "prerequisite":         "<what is needed e.g. 'Proxmox server already available' or 'none'>",
      "trade_off":            "<honest downside e.g. 'Requires self-maintenance' or 'Lower content library'>",
      "adel_fit_score":       "high | medium | low",
      "note":                 "<one-line rationale>"
    }}
  ],

  "chart_data": {{
    "spending_by_category_pie": [
      {{"label": "<category>", "value": 0.0, "percentage": 0.0}}
    ],
    "income_vs_expenses_bar": [
      {{"month": "<YYYY-MM>", "income": 0.0, "expenses": 0.0, "savings": 0.0}}
    ],
    "savings_progress_line": [
      {{"month": "<YYYY-MM>", "cumulative_savings": 0.0, "target_line": 0.0}}
    ]
  }},

  "reasoning": "<Plain-text explanation (3–8 sentences) of how you derived the results: which months had data, how many transactions you found, how income and expenses were computed, whether pre-computed values were used, and any data gaps or caveats that affected the output. Be specific — mention actual amounts and months. This field is shown directly to the user as a transparency log.>"
}}

<bank-statement>
{statement}
</bank-statement>
"""
        return prompt
