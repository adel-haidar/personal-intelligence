"""Transactional email — SES-ready abstraction.

For now there is no SES/SMTP integration in this deployment, so these functions
just log the actionable URL at INFO (visible in `journalctl`) and return True.
A future SES implementation only needs to fill in `_send` — the link-building
and call sites stay the same.

These functions NEVER raise: a notification failure must not break registration,
verification, or password reset. Tokens appear in logs by necessity (so an
operator can hand a link to a user before SES exists) but raw passwords and
password hashes are never logged anywhere.
"""

import logging

from private_internet.config import get_settings

logger = logging.getLogger(__name__)


def _send(to: str, subject: str, body: str) -> bool:
    """The single swap-point for a real provider (SES/SMTP). Today: log only."""
    try:
        logger.info("EMAIL → %s | %s\n%s", to, subject, body)
        return True
    except Exception:  # pragma: no cover - logging should never fail
        logger.exception("Failed to dispatch email to %s", to)
        return False


def send_verification_email(to: str, token: str) -> bool:
    settings = get_settings()
    link = f"{settings.base_url}/api/auth/verify-email?token={token}"
    return _send(
        to,
        "Verify your Private Internet email",
        f"Confirm your account by visiting:\n{link}\n\n"
        f"This link expires in {settings.verification_token_ttl_hours} hours.",
    )


def send_password_reset_email(to: str, token: str) -> bool:
    settings = get_settings()
    link = f"{settings.base_url}/reset-password?token={token}"
    return _send(
        to,
        "Reset your Private Internet password",
        f"Reset your password by visiting:\n{link}\n\n"
        f"This link expires in {settings.reset_token_ttl_hours} hour(s). "
        f"If you did not request this, ignore this email.",
    )


def send_welcome_email(to: str, display_name: str) -> bool:
    settings = get_settings()
    return _send(
        to,
        "Welcome to Private Internet",
        f"Hi {display_name},\n\n"
        f"Your private AI brain is being set up. Sign in at {settings.base_url} "
        f"to get started.",
    )
