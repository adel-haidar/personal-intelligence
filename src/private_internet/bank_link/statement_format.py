"""Render GoCardless account data into German-statement text.

The output is consumed UNCHANGED by the existing BankAdviser
(agents/assistant/banking/bank_adviser.py) and the MemoryClient bank-statement
detector (agents/assistant/shared/memory_client.py). To keep that contract, the
rendered text MUST satisfy three regexes, verified by tests:

  • Month header   — memory_client._STATEMENT_HEADER_RE: ``Kontoauszug MM/YYYY``
                     (the number is read as the calendar month).
  • Balance lines  — bank_adviser._BALANCE_LINE_RE: a line containing
                     ``Kontostand … am DD.MM.YYYY … <amount>`` where the German
                     amount is the LAST token (optional trailing sign).
  • Transaction    — bank_adviser._TXN_LINE_RE: a standalone amount ALONE on its
                     own line. Debits carry a leading ``-``; credits are unsigned.

Counterparty / purpose text always goes on its own line(s) and always contains
letters, so it never collides with the standalone-amount transaction regex.

We also synthesise an opening balance dated to the LAST DAY OF THE PRIOR MONTH so
that bank_adviser._balance_net_for_month trusts it as a genuine opening balance
(its date is strictly before the statement month) and can cross-validate the
transaction sums.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass
class Txn:
    """A normalised transaction. `amount` is signed: negative = debit (money out)."""
    date: date
    amount: float
    description: str


def format_german_amount(value: float) -> str:
    """Format a non-negative magnitude as German currency text, e.g. 1234.5 → '1.234,50'.

    The sign is rendered separately by the caller (leading '-' for debits, none
    for credits) so the output matches the Sparkasse layout the adviser parses.
    """
    cents = int(round(abs(value) * 100))
    euros, rem = divmod(cents, 100)
    grouped = f"{euros:,}".replace(",", ".")  # thousands sep '.'
    return f"{grouped},{rem:02d}"


def _prev_month_last_day(year: int, month: int) -> date:
    """Last calendar day of the month before (year, month)."""
    if month == 1:
        py, pm = year - 1, 12
    else:
        py, pm = year, month - 1
    return date(py, pm, calendar.monthrange(py, pm)[1])


def render_statement(
    *,
    month: str,
    bank_name: str,
    iban: str,
    currency: str,
    closing_balance: float | None,
    transactions: list[Txn],
) -> str:
    """Render one account-month into adviser-compatible German statement text.

    Args:
        month: 'YYYY-MM'.
        bank_name: e.g. 'Sparkasse Köln Bonn' (kept in the header for keyword
            detection + human readability).
        iban: account IBAN (or '' if unknown).
        currency: ISO code, e.g. 'EUR'.
        closing_balance: latest known balance, or None if unavailable.
        transactions: transactions booked within `month` (any order).
    """
    year, mon = (int(p) for p in month.split("-"))
    txns = sorted(transactions, key=lambda t: t.date)

    net = sum(t.amount for t in txns)
    opening_balance = None if closing_balance is None else closing_balance - net

    lines: list[str] = []
    # Header — sets the statement month and seeds banking keywords (Kontoauszug,
    # Konto, IBAN, Girokonto, Saldo) so _looks_like_bank_statement matches.
    lines.append(f"Kontoauszug {mon:02d}/{year}")
    lines.append(bank_name or "Bank")
    lines.append(f"Girokonto IBAN: {iban or 'unbekannt'} ({currency})")
    lines.append("Automatisch importiert via Private Internet Bankanbindung.")
    lines.append("")

    if opening_balance is not None:
        opening_date = _prev_month_last_day(year, mon)
        lines.append(_balance_line("Kontostand", opening_date, opening_balance))
        lines.append("")

    for t in txns:
        desc = " ".join((t.description or "Buchung").split()) or "Buchung"
        lines.append(f"{t.date.strftime('%d.%m.%Y')}  {desc}")
        # Standalone amount line: debit = leading '-', credit = unsigned.
        sign = "-" if t.amount < 0 else ""
        lines.append(f"{sign}{format_german_amount(t.amount)}")

    if closing_balance is not None:
        closing_date = txns[-1].date if txns else date(year, mon, calendar.monthrange(year, mon)[1])
        lines.append("")
        lines.append(_balance_line("Kontostand", closing_date, closing_balance))

    return "\n".join(lines)


def _balance_line(label: str, when: date, value: float) -> str:
    """Build a ``Kontostand am DD.MM.YYYY   <amount>[ -]`` line.

    The amount is the last token; a negative balance gets a trailing ' -' so
    bank_adviser._BALANCE_LINE_RE captures the sign.
    """
    amount = format_german_amount(value)
    trailing = " -" if value < 0 else ""
    return f"{label} am {when.strftime('%d.%m.%Y')}      {amount}{trailing}"
