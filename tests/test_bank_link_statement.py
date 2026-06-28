"""The bank-link daily poll renders GoCardless data into German-statement text.

That text is fed UNCHANGED to the existing BankAdviser. These tests pin the
contract: whatever render_statement emits must round-trip cleanly through the
adviser's deterministic parsers and the MemoryClient bank-statement detector.
If either side's regexes change, this test fails — which is exactly the signal
we want, because the daily poll would otherwise silently feed garbage to the
brain.
"""
from datetime import date

from assistant.banking.bank_adviser import (
    _balance_net_for_month,
    _extract_balances,
    _extract_transaction_totals,
)
from assistant.shared.memory_client import MemoryClient

from private_internet.bank_link.statement_format import (
    Txn,
    format_german_amount,
    render_statement,
)

_TXNS = [
    Txn(date(2026, 6, 2), -49.90, "EDEKA Einkauf Lebensmittel"),
    Txn(date(2026, 6, 5), 2500.00, "Gehalt Arbeitgeber GmbH"),
    Txn(date(2026, 6, 12), -1200.00, "Miete Vermieter"),
    Txn(date(2026, 6, 20), -15.00, "Spotify Abo"),
]
_CLOSING = 3235.10
_EXP_CREDITS = 2500.00
_EXP_DEBITS = 49.90 + 1200.00 + 15.00


def _render():
    return render_statement(
        month="2026-06",
        bank_name="Sparkasse Köln Bonn",
        iban="DE89370400440532013000",
        currency="EUR",
        closing_balance=_CLOSING,
        transactions=_TXNS,
    )


def test_format_german_amount():
    assert format_german_amount(1234.5) == "1.234,50"
    assert format_german_amount(0) == "0,00"
    assert format_german_amount(-49.9) == "49,90"  # magnitude only; caller adds sign
    assert format_german_amount(1234567.89) == "1.234.567,89"


def test_transaction_totals_round_trip():
    credits, debits = _extract_transaction_totals(_render())
    assert credits == _EXP_CREDITS
    assert round(debits, 2) == round(_EXP_DEBITS, 2)


def test_balances_and_net():
    text = _render()
    balances = _extract_balances(text)
    # A synthesised opening (prior-month) balance + the live closing balance.
    assert len(balances) == 2
    opening_date, opening = balances[0]
    assert opening_date < date(2026, 6, 1)  # must predate the month to be trusted
    # Opening + net == closing, by construction.
    assert round(opening + (_EXP_CREDITS - _EXP_DEBITS), 2) == _CLOSING

    net = _balance_net_for_month(text, "2026-06")
    assert net is not None
    assert round(net, 2) == round(_EXP_CREDITS - _EXP_DEBITS, 2)


def test_detected_as_bank_statement_for_correct_month():
    mc = MemoryClient.__new__(MemoryClient)
    item = {"title": "Kontoauszug Sparkasse Köln Bonn 2026-06", "content": _render()}
    assert MemoryClient._looks_like_bank_statement(mc, item) is True
    assert MemoryClient._statement_month(mc, item) == "2026-06"


def test_no_closing_balance_falls_back_to_txn_sums():
    # Prior months get closing_balance=None → no trusted balance delta, adviser
    # falls back to transaction sums. The text must still parse as a statement.
    text = render_statement(
        month="2026-05", bank_name="Volksbank", iban="", currency="EUR",
        closing_balance=None, transactions=[Txn(date(2026, 5, 9), -20.0, "Test")],
    )
    assert _balance_net_for_month(text, "2026-05") is None
    credits, debits = _extract_transaction_totals(text)
    assert credits == 0.0 and debits == 20.0


def test_negative_balance_renders_trailing_sign():
    text = render_statement(
        month="2026-06", bank_name="Sparkasse", iban="", currency="EUR",
        closing_balance=-150.0, transactions=[Txn(date(2026, 6, 3), -200.0, "Lastschrift")],
    )
    balances = _extract_balances(text)
    closing = balances[-1][1]
    assert closing == -150.0
