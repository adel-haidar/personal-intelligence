"""Tests for email/password user auth: password hashing + auth router."""

import json
from unittest.mock import patch

import pytest

from private_internet.users.passwords import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)
from private_internet.users.routes import (
    LoginRequest,
    OnboardingRequest,
    RegisterRequest,
    login,
    register,
    update_onboarding,
)
from private_internet.core.request_context import RequestContext

_GOOD_PW = "correct-horse-battery"  # ≥ 12 chars


class _Settings:
    def __init__(self, registration_open=True, max_users=0,
                 require_email_verification=False):
        self.registration_open = registration_open
        self.max_users = max_users
        self.require_email_verification = require_email_verification
        self.verification_token_ttl_hours = 24
        self.reset_token_ttl_hours = 1
        self.app_domain = "test.example.com"

    @property
    def base_url(self):
        return f"https://{self.app_domain}"


class _FakeRequest:
    """Minimal stand-in for fastapi.Request for the rate limiter / IP extraction."""
    def __init__(self, ip="203.0.113.7"):
        self.headers = {}
        self.client = type("C", (), {"host": ip})()


class _FakeBackground:
    """Captures add_task calls instead of scheduling them."""
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _body(resp):
    return json.loads(resp.body)


def _reset_rate_limits():
    from private_internet.users import routes as _r
    _r._RATE_BUCKETS.clear()


# ── password hashing ───────────────────────────────────────────

class TestPasswordHashing:
    def test_round_trip(self):
        stored = hash_password(_GOOD_PW)
        assert stored.startswith("scrypt$")
        assert verify_password(_GOOD_PW, stored) is True

    def test_wrong_password_fails(self):
        stored = hash_password(_GOOD_PW)
        assert verify_password("not-the-password!", stored) is False

    def test_salt_makes_hashes_unique(self):
        assert hash_password(_GOOD_PW) != hash_password(_GOOD_PW)

    def test_malformed_or_missing_stored_is_false(self):
        assert verify_password(_GOOD_PW, None) is False
        assert verify_password(_GOOD_PW, "") is False
        assert verify_password(_GOOD_PW, "garbage") is False
        assert verify_password(_GOOD_PW, "bcrypt$x$y") is False

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            hash_password("a" * (MIN_PASSWORD_LENGTH - 1))


# ── register ───────────────────────────────────────────────────

class TestRegister:
    def setup_method(self):
        _reset_rate_limits()

    @pytest.mark.anyio
    async def test_happy_path(self):
        created = {"id": "u-123", "email": "lena@example.com", "display_name": "Lena",
                   "is_admin": False, "onboarding_completed": False, "onboarding_step": 0}
        background = _FakeBackground()
        with (
            patch("private_internet.users.routes.get_settings", return_value=_Settings()),
            patch("private_internet.users.routes.count_users", return_value=0),
            patch("private_internet.users.routes.get_user_by_email", return_value=None),
            patch("private_internet.users.routes.create_user", return_value=created) as mock_create,
            patch("private_internet.users.routes.set_verification_token", return_value="vtok"),
            patch("private_internet.users.routes.send_verification_email") as mock_send,
            patch("private_internet.users.routes.create_user_token", return_value="jwt-tok"),
        ):
            result = await register(
                RegisterRequest(
                    email="Lena@Example.com", display_name="Lena",
                    password=_GOOD_PW, referral_source="a friend",
                ),
                _FakeRequest(),
                background,
            )

        assert result["token"] == "jwt-tok"
        assert result["user"]["id"] == "u-123"
        assert result["email_verification_required"] is False
        # email normalized to lowercase before persistence
        assert mock_create.call_args.kwargs["email"] == "lena@example.com"
        # verification email dispatched with the generated token
        mock_send.assert_called_once_with("lena@example.com", "vtok")
        # provisioning (which seeds the welcome memory) is scheduled in background
        assert background.tasks and background.tasks[0][1][0]["id"] == "u-123"

    @pytest.mark.anyio
    async def test_verification_required_returns_no_token(self):
        created = {"id": "u-9", "email": "v@example.com", "display_name": "V"}
        background = _FakeBackground()
        with (
            patch("private_internet.users.routes.get_settings",
                  return_value=_Settings(require_email_verification=True)),
            patch("private_internet.users.routes.count_users", return_value=0),
            patch("private_internet.users.routes.get_user_by_email", return_value=None),
            patch("private_internet.users.routes.create_user", return_value=created),
            patch("private_internet.users.routes.set_verification_token", return_value="vtok"),
            patch("private_internet.users.routes.send_verification_email"),
            patch("private_internet.users.routes.create_user_token", return_value="jwt-tok"),
        ):
            resp = await register(
                RegisterRequest(email="v@example.com", display_name="V", password=_GOOD_PW),
                _FakeRequest(), background,
            )
        assert resp.status_code == 201
        body = _body(resp)
        assert body["email_verification_required"] is True
        assert "token" not in body

    @pytest.mark.anyio
    async def test_duplicate_email_409(self):
        with (
            patch("private_internet.users.routes.get_settings", return_value=_Settings()),
            patch("private_internet.users.routes.count_users", return_value=0),
            patch("private_internet.users.routes.get_user_by_email", return_value={"id": "x"}),
        ):
            resp = await register(
                RegisterRequest(email="dup@example.com", display_name="Dup", password=_GOOD_PW),
                _FakeRequest(), _FakeBackground(),
            )
        assert resp.status_code == 409
        assert "already exists" in _body(resp)["error"]

    @pytest.mark.anyio
    async def test_registration_closed_403(self):
        with patch("private_internet.users.routes.get_settings",
                   return_value=_Settings(registration_open=False)):
            resp = await register(
                RegisterRequest(email="x@example.com", display_name="X", password=_GOOD_PW),
                _FakeRequest(), _FakeBackground(),
            )
        assert resp.status_code == 403
        assert "invite-only" in _body(resp)["error"]

    @pytest.mark.anyio
    async def test_max_users_403(self):
        with (
            patch("private_internet.users.routes.get_settings", return_value=_Settings(max_users=5)),
            patch("private_internet.users.routes.count_users", return_value=5),
        ):
            resp = await register(
                RegisterRequest(email="x@example.com", display_name="X", password=_GOOD_PW),
                _FakeRequest(), _FakeBackground(),
            )
        assert resp.status_code == 403
        assert "limit reached" in _body(resp)["error"]

    @pytest.mark.anyio
    async def test_short_password_422(self):
        with (
            patch("private_internet.users.routes.get_settings", return_value=_Settings()),
            patch("private_internet.users.routes.count_users", return_value=0),
        ):
            resp = await register(
                RegisterRequest(email="x@example.com", display_name="X", password="short"),
                _FakeRequest(), _FakeBackground(),
            )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_ip_rate_limit_429(self):
        req = _FakeRequest(ip="198.51.100.5")
        with (
            patch("private_internet.users.routes.get_settings", return_value=_Settings()),
            patch("private_internet.users.routes.count_users", return_value=0),
            patch("private_internet.users.routes.get_user_by_email", return_value=None),
            patch("private_internet.users.routes.create_user",
                  return_value={"id": "u", "email": "a@b.com", "display_name": "A"}),
            patch("private_internet.users.routes.set_verification_token", return_value="t"),
            patch("private_internet.users.routes.send_verification_email"),
            patch("private_internet.users.routes.create_user_token", return_value="jwt"),
        ):
            last = None
            for i in range(6):
                last = await register(
                    RegisterRequest(email=f"u{i}@example.com", display_name="A", password=_GOOD_PW),
                    req, _FakeBackground(),
                )
        assert last.status_code == 429
        assert "Retry-After" in last.headers

    @pytest.mark.anyio
    async def test_login_unverified_403_when_required(self):
        user = {"id": "u-1", "email": "a@b.com", "display_name": "A",
                "email_verified": False, "password_hash": hash_password(_GOOD_PW)}
        with (
            patch("private_internet.users.routes.get_settings",
                  return_value=_Settings(require_email_verification=True)),
            patch("private_internet.users.routes.get_user_by_email", return_value=user),
        ):
            resp = await login(LoginRequest(email="a@b.com", password=_GOOD_PW))
        assert resp.status_code == 403
        assert _body(resp)["error"] == "email_not_verified"


# ── login ──────────────────────────────────────────────────────

class TestLogin:
    @pytest.mark.anyio
    async def test_unknown_email_404(self):
        with patch("private_internet.users.routes.get_user_by_email", return_value=None):
            resp = await login(LoginRequest(email="nobody@example.com", password=_GOOD_PW))
        assert resp.status_code == 404
        assert "No account found" in _body(resp)["error"]

    @pytest.mark.anyio
    async def test_wrong_password_401(self):
        user = {"id": "u-1", "email": "a@b.com", "password_hash": hash_password(_GOOD_PW)}
        with patch("private_internet.users.routes.get_user_by_email", return_value=user):
            resp = await login(LoginRequest(email="a@b.com", password="wrong-password!!"))
        assert resp.status_code == 401
        assert _body(resp)["error"] == "Incorrect password."

    @pytest.mark.anyio
    async def test_success_strips_hash_and_returns_token(self):
        user = {"id": "u-1", "email": "a@b.com", "display_name": "A",
                "password_hash": hash_password(_GOOD_PW)}
        with (
            patch("private_internet.users.routes.get_user_by_email", return_value=user),
            patch("private_internet.users.routes.touch_last_active") as mock_touch,
            patch("private_internet.users.routes.create_user_token", return_value="jwt-tok"),
        ):
            result = await login(LoginRequest(email="A@B.com", password=_GOOD_PW))
        assert result["token"] == "jwt-tok"
        assert "password_hash" not in result["user"]
        mock_touch.assert_called_once_with("u-1")


# ── onboarding ─────────────────────────────────────────────────

class TestOnboarding:
    @pytest.mark.anyio
    async def test_updates_only_provided_fields(self):
        ctx = RequestContext(user_id="u-1", user_email="a@b.com", is_admin=False)
        updated = {"id": "u-1", "onboarding_step": 3, "onboarding_completed": False}
        with patch("private_internet.users.routes.update_user", return_value=updated) as mock_upd:
            result = await update_onboarding(OnboardingRequest(onboarding_step=3), ctx=ctx)
        assert result["user"]["onboarding_step"] == 3
        assert mock_upd.call_args.args[0] == "u-1"
        assert mock_upd.call_args.kwargs == {"onboarding_step": 3}

    @pytest.mark.anyio
    async def test_empty_update_422(self):
        ctx = RequestContext(user_id="u-1", user_email="a@b.com", is_admin=False)
        resp = await update_onboarding(OnboardingRequest(), ctx=ctx)
        assert resp.status_code == 422
