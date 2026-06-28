"""Bank-link orchestration: consent flow + daily sync.

Flow:
  build_authorize(institution_id, user_id)
      → create a GoCardless requisition, persist a 'pending' connection,
        return the consent link (the bank's login page).
  handle_callback(reference)
      → verify the signed state, read the granted account ids, mark 'connected',
        run an initial sync.
  sync_connection(user_id)
      → for each account: fetch balances + transactions, render a German
        statement per month, UPSERT it into the brain (one memory per month).
  poll_all_users()
      → nightly fan-out over every connected user.

Reuses:
  • the signed-HMAC state pattern from connectors/service.py (stateless callback),
  • memory.service.save_memory / delete_memory (pgvector brain),
  • core.jobs.run_for_all_users for the fan-out.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import date, datetime, timezone

from private_internet.bank_link import db, gocardless
from private_internet.bank_link.statement_format import Txn, render_statement
from private_internet.config import get_settings
from private_internet.memory.service import delete_memory, save_memory

logger = logging.getLogger(__name__)


# ── Signed state (mirrors connectors/service.py) ──────────────────────────────

def _secret() -> str:
    return get_settings().secret_key or "insecure-fallback-set-secret-key"


def build_state(user_id: str) -> str:
    """Signed, stateless reference passed to GoCardless and echoed back."""
    payload = json.dumps({"u": user_id}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(_secret().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_state(state: str) -> str | None:
    """Return the user_id encoded in a state token, or None if tampered."""
    try:
        payload_b64, sig = state.rsplit(".", 1)
        expected = hmac.new(_secret().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        pad = 4 - len(payload_b64) % 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * pad))
        return payload["u"]
    except Exception:
        return None


# ── Consent flow ──────────────────────────────────────────────────────────────

def _redirect_uri() -> str:
    return f"{get_settings().base_url}/api/bank/callback"


def build_authorize(institution_id: str, user_id: str, *, institution_name: str | None = None) -> str:
    """Create a requisition and return the bank consent URL."""
    reference = build_state(user_id)
    requisition = gocardless.create_requisition(
        institution_id, redirect=_redirect_uri(), reference=reference
    )
    db.upsert_pending_connection(
        user_id,
        institution_id=institution_id,
        institution_name=institution_name,
        requisition_id=requisition["id"],
    )
    link = requisition.get("link")
    if not link:
        raise RuntimeError("GoCardless requisition returned no consent link")
    logger.info("[bank] [user:%s] requisition %s created", user_id[:8], requisition["id"])
    return link


def handle_callback(reference: str) -> str:
    """Resolve the consent callback. Returns the user_id for the redirect."""
    user_id = verify_state(reference)
    if user_id is None:
        raise ValueError("Invalid or tampered bank callback reference")

    conn = db.get_connection(user_id)
    if conn is None:
        raise ValueError("No pending bank connection for this user")

    requisition = gocardless.get_requisition(conn["requisition_id"])
    account_ids = requisition.get("accounts", []) or []
    if not account_ids:
        db.update_sync_result(
            user_id, status="error",
            last_error="Bank consent completed but no accounts were granted.",
        )
        logger.warning("[bank] [user:%s] callback with no accounts", user_id[:8])
        return user_id

    db.mark_connected(user_id, account_ids=account_ids, consent_expires_at=None)
    logger.info("[bank] [user:%s] connected (%d account(s))", user_id[:8], len(account_ids))

    # Initial sync — best effort; failure leaves status updated but not fatal.
    try:
        sync_connection(user_id)
    except Exception:
        logger.error("[bank] [user:%s] initial sync failed", user_id[:8], exc_info=True)
    return user_id


# ── Sync ──────────────────────────────────────────────────────────────────────

def _parse_amount(txn: dict) -> float | None:
    try:
        return float(txn["transactionAmount"]["amount"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_date(txn: dict) -> date | None:
    raw = txn.get("bookingDate") or txn.get("valueDate")
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _describe(txn: dict) -> str:
    parts = txn.get("remittanceInformationUnstructuredArray")
    if isinstance(parts, list) and parts:
        info = " ".join(str(p) for p in parts)
    else:
        info = txn.get("remittanceInformationUnstructured") or ""
    name = txn.get("creditorName") or txn.get("debtorName") or ""
    desc = " ".join(x for x in (name, info) if x).strip()
    return desc or "Buchung"


def _pick_balance(balances: list[dict]) -> float | None:
    """Pick the most representative current balance from a balances array."""
    if not balances:
        return None
    preferred = ("closingBooked", "interimAvailable", "expected", "interimBooked")
    by_type = {b.get("balanceType"): b for b in balances}
    for t in preferred:
        if t in by_type:
            try:
                return float(by_type[t]["balanceAmount"]["amount"])
            except (KeyError, TypeError, ValueError):
                continue
    try:
        return float(balances[0]["balanceAmount"]["amount"])
    except (KeyError, TypeError, ValueError):
        return None


def _months_to_sync(today: date) -> list[str]:
    """Current month, plus the previous month during the first 5 days so a fresh
    month boundary doesn't briefly drop the prior month's data."""
    months = [today.strftime("%Y-%m")]
    if today.day <= 5:
        py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        months.append(f"{py:04d}-{pm:02d}")
    return months


def sync_connection(user_id: str, *, _today: date | None = None) -> dict:
    """Poll every account of a user's bank and refresh its statement memories.

    Returns a small summary dict. Raises on hard failure (caller records 'error').
    """
    today = _today or datetime.now(timezone.utc).date()
    conn = db.get_connection(user_id)
    if conn is None or conn["status"] not in ("connected", "error"):
        raise ValueError("No connected bank for this user")

    account_ids = conn["account_ids"] or []
    bank_name = conn.get("institution_name") or "Bank"
    months = _months_to_sync(today)

    statements_written = 0
    latest_balance: float | None = None

    for account_id in account_ids:
        details = {}
        try:
            details = gocardless.get_details(account_id)
        except Exception:
            logger.warning("[bank] [user:%s] details failed for %s", user_id[:8], account_id[:8])
        iban = details.get("iban", "")
        currency = details.get("currency", "EUR")

        balance = _pick_balance(gocardless.get_balances(account_id))
        if balance is not None:
            latest_balance = balance

        raw_txns = gocardless.get_transactions(account_id)
        normalised: list[Txn] = []
        for raw in raw_txns:
            amount = _parse_amount(raw)
            when = _parse_date(raw)
            if amount is None or when is None:
                continue
            normalised.append(Txn(date=when, amount=amount, description=_describe(raw)))

        for month in months:
            month_txns = [t for t in normalised if t.date.strftime("%Y-%m") == month]
            # closing_balance only applies to the current month (the live balance
            # is "now"); prior months get None and fall back to transaction sums.
            closing = balance if month == today.strftime("%Y-%m") else None
            if not month_txns and closing is None:
                continue
            text = render_statement(
                month=month, bank_name=bank_name, iban=iban, currency=currency,
                closing_balance=closing, transactions=month_txns,
            )
            _upsert_statement_memory(user_id, account_id, month, bank_name, text)
            statements_written += 1

    db.update_sync_result(
        user_id, status="connected", last_balance=latest_balance,
        last_error=None, set_synced_now=True,
    )
    logger.info(
        "[bank] [user:%s] synced %d statement(s) across %d account(s)",
        user_id[:8], statements_written, len(account_ids),
    )
    return {"statements": statements_written, "accounts": len(account_ids)}


def _upsert_statement_memory(
    user_id: str, account_id: str, month: str, bank_name: str, text: str
) -> None:
    """Replace the (user, account, month) brain memory with fresh statement text."""
    existing = db.get_statement_memory_id(user_id, account_id, month)
    if existing:
        # The month grows daily — delete the stale snapshot and re-save so the
        # adviser never sees two statements for the same month.
        try:
            delete_memory(existing, user_id=user_id)
        except Exception:
            logger.warning("[bank] [user:%s] failed to delete stale memory %s", user_id[:8], existing)

    title = f"Kontoauszug {bank_name} {month}"
    memory = save_memory(
        title=title,
        content=text,
        tags=["bank-link", "bank-statement", month],
        user_id=user_id,
    )
    db.upsert_statement_memory_id(user_id, account_id, month, memory.memory_id)


# ── Disconnect ────────────────────────────────────────────────────────────────

def disconnect(user_id: str) -> None:
    """Revoke the GoCardless requisition and drop the connection rows.

    Brain memories are intentionally left in place (financial history persists).
    """
    conn = db.get_connection(user_id)
    if conn and conn.get("requisition_id"):
        gocardless.delete_requisition(conn["requisition_id"])
    db.delete_connection(user_id)
    logger.info("[bank] [user:%s] disconnected", user_id[:8])


# ── Status (for the dashboard) ────────────────────────────────────────────────

def get_status(user_id: str) -> dict:
    """Return the user's bank-connection status for the Finances UI."""
    conn = db.get_connection(user_id)
    if conn is None:
        return {"connected": False, "configured": gocardless.is_configured()}
    return {
        "connected": conn["status"] == "connected",
        "configured": gocardless.is_configured(),
        "status": conn["status"],
        "institution_name": conn.get("institution_name"),
        "institution_id": conn.get("institution_id"),
        "account_count": len(conn.get("account_ids") or []),
        "last_sync_at": conn["last_sync_at"].isoformat() if conn.get("last_sync_at") else None,
        "last_balance": float(conn["last_balance"]) if conn.get("last_balance") is not None else None,
        "consent_expires_at": (
            conn["consent_expires_at"].isoformat() if conn.get("consent_expires_at") else None
        ),
        "last_error": conn.get("last_error"),
    }


# ── Daily fan-out ─────────────────────────────────────────────────────────────

def poll_all_users() -> dict:
    """Nightly poll across every connected user.

    Restricted to users with a connected bank (not every onboarded user); one
    user's failure is recorded as 'error' and never aborts the rest.
    """
    user_ids = db.list_connected_user_ids()
    succeeded = 0
    failed = 0
    for user_id in user_ids:
        try:
            sync_connection(user_id)
            succeeded += 1
        except Exception as exc:
            failed += 1
            db.update_sync_result(user_id, status="error", last_error=str(exc)[:500])
            logger.error("[bank] [user:%s] nightly sync failed: %s", user_id[:8], exc, exc_info=True)
    logger.info("[bank] nightly poll — %d ok, %d failed, %d total", succeeded, failed, len(user_ids))
    return {"users": len(user_ids), "succeeded": succeeded, "failed": failed}
