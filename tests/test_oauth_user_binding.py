"""OAuth → platform-user binding (Section: per-user MCP brain scoping).

These are DB-free unit tests: psycopg2 connections are mocked. They assert that

  * an access token bound to user A resolves to A,
  * the INTERNAL_SECRET path resolves to the seed admin (UNCHANGED),
  * a legacy/unbound token falls back to the seed admin,
  * the /.well-known discovery docs are byte-for-byte unchanged,
  * the OAuth flow propagates the user binding code → token.
"""

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── mcp_server imports init_db() at module top level (hits the DB). Stub the DB
#    layer it touches BEFORE importing so these stay DB-free. ─────────────────
def _import_mcp_server():
    with (
        patch("private_internet.memory.service.init_db", MagicMock()),
        patch("private_internet.memory.service._connect", MagicMock()),
    ):
        # Force a fresh import so the patched init_db is what runs at import.
        sys.modules.pop("private_internet.memory.mcp_server", None)
        import private_internet.memory.mcp_server as mod
        return mod


# ── resolve_token_user (auth/oauth.py) ──────────────────────────────────────

def _mock_conn(fetchone_row):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_row
    conn.cursor.return_value = cur
    return conn


class TestResolveTokenUser:
    def test_bound_token_returns_user_id(self):
        from private_internet.auth import oauth
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        conn = _mock_conn(("user-A-uuid", future))
        with patch.object(oauth, "_connect", return_value=conn):
            assert oauth.resolve_token_user("tok") == "user-A-uuid"

    def test_unbound_token_returns_none(self):
        from private_internet.auth import oauth
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        conn = _mock_conn((None, future))  # valid token, no user binding
        with patch.object(oauth, "_connect", return_value=conn):
            assert oauth.resolve_token_user("tok") is None

    def test_expired_token_returns_none(self):
        from private_internet.auth import oauth
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        conn = _mock_conn(("user-A-uuid", past))
        with patch.object(oauth, "_connect", return_value=conn):
            assert oauth.resolve_token_user("tok") is None

    def test_unknown_token_returns_none(self):
        from private_internet.auth import oauth
        conn = _mock_conn(None)
        with patch.object(oauth, "_connect", return_value=conn):
            assert oauth.resolve_token_user("nope") is None

    def test_validate_token_still_returns_client_id(self):
        # The legacy contract (client_id) must remain intact for other callers.
        from private_internet.auth import oauth
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        conn = _mock_conn(("client-xyz", future))
        with patch.object(oauth, "_connect", return_value=conn):
            assert oauth.validate_token("tok") == "client-xyz"


# ── _mcp_user_id (memory/mcp_server.py) ─────────────────────────────────────

class TestMcpUserId:
    def test_oauth_token_bound_to_user_resolves_to_that_user(self):
        mod = _import_mcp_server()
        access = SimpleNamespace(client_id="claude-client", subject="user-A-uuid")
        with (
            patch.object(mod, "get_access_token", return_value=access),
            patch("private_internet.users.service.get_seed_admin_id",
                  return_value="seed-admin-uuid"),
        ):
            assert mod._mcp_user_id() == "user-A-uuid"

    def test_internal_secret_resolves_to_seed_admin(self):
        mod = _import_mcp_server()
        # INTERNAL_SECRET callers get the sentinel client_id and no subject.
        access = SimpleNamespace(client_id=mod._INTERNAL_CLIENT_ID, subject=None)
        with (
            patch.object(mod, "get_access_token", return_value=access),
            patch("private_internet.users.service.get_seed_admin_id",
                  return_value="seed-admin-uuid"),
        ):
            assert mod._mcp_user_id() == "seed-admin-uuid"

    def test_internal_secret_with_stray_subject_still_seed_admin(self):
        # Defense in depth: even if a subject were somehow present, the internal
        # sentinel must never resolve to a non-admin user.
        mod = _import_mcp_server()
        access = SimpleNamespace(client_id=mod._INTERNAL_CLIENT_ID, subject="user-X")
        with (
            patch.object(mod, "get_access_token", return_value=access),
            patch("private_internet.users.service.get_seed_admin_id",
                  return_value="seed-admin-uuid"),
        ):
            assert mod._mcp_user_id() == "seed-admin-uuid"

    def test_legacy_unbound_token_falls_back_to_seed_admin(self):
        mod = _import_mcp_server()
        access = SimpleNamespace(client_id="claude-client", subject=None)
        with (
            patch.object(mod, "get_access_token", return_value=access),
            patch("private_internet.users.service.get_seed_admin_id",
                  return_value="seed-admin-uuid"),
        ):
            assert mod._mcp_user_id() == "seed-admin-uuid"

    def test_no_auth_context_falls_back_to_seed_admin(self):
        mod = _import_mcp_server()
        with (
            patch.object(mod, "get_access_token", return_value=None),
            patch("private_internet.users.service.get_seed_admin_id",
                  return_value="seed-admin-uuid"),
        ):
            assert mod._mcp_user_id() == "seed-admin-uuid"


# ── verify_token sets the binding on the AccessToken ────────────────────────

class TestVerifyTokenBinding:
    @pytest.mark.anyio
    async def test_internal_secret_token_tagged_sentinel_no_subject(self):
        mod = _import_mcp_server()
        verifier = mod.PostgresTokenVerifier()
        with patch.dict("os.environ", {"INTERNAL_SECRET": "shh-secret"}):
            access = await verifier.verify_token("shh-secret")
        assert access is not None
        assert access.client_id == mod._INTERNAL_CLIENT_ID
        assert access.subject is None

    @pytest.mark.anyio
    async def test_oauth_token_carries_resolved_subject(self):
        mod = _import_mcp_server()
        verifier = mod.PostgresTokenVerifier()
        with (
            patch.dict("os.environ", {"INTERNAL_SECRET": "shh-secret"}),
            patch.object(mod, "check_token", return_value="claude-client"),
            patch.object(mod, "resolve_token_user", return_value="user-A-uuid"),
        ):
            access = await verifier.verify_token("a-real-oauth-token")
        assert access is not None
        assert access.client_id == "claude-client"
        assert access.subject == "user-A-uuid"

    @pytest.mark.anyio
    async def test_invalid_token_rejected(self):
        mod = _import_mcp_server()
        verifier = mod.PostgresTokenVerifier()
        with (
            patch.dict("os.environ", {"INTERNAL_SECRET": "shh-secret"}),
            patch.object(mod, "check_token", return_value=None),
        ):
            access = await verifier.verify_token("garbage")
        assert access is None


# ── OAuth flow: code → token binding propagation ────────────────────────────

class TestFlowBindingPropagation:
    def test_create_auth_code_persists_user_id(self):
        from private_internet.auth import oauth
        conn = _mock_conn(None)
        cur = conn.cursor.return_value
        with patch.object(oauth, "_connect", return_value=conn):
            oauth.create_auth_code("client", "challenge", "https://cb", user_id="user-A")
        insert_sql, params = cur.execute.call_args.args
        assert "user_id" in insert_sql
        assert params[-1] == "user-A"

    def test_exchange_code_copies_user_id_to_tokens(self):
        from private_internet.auth import oauth
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        conn = MagicMock()
        cur = MagicMock()
        # SELECT returns: code_challenge, redirect_uri, expires_at, used, user_id
        cur.fetchone.return_value = ("chal", "https://cb", future, False, "user-A")
        conn.cursor.return_value = cur
        with (
            patch.object(oauth, "_connect", return_value=conn),
            patch.object(oauth, "verify_pkce", return_value=True),
        ):
            result = oauth.exchange_code("code", "verifier", "client")
        assert result is not None
        # Find the two INSERT INTO oauth_tokens calls and assert user_id == user-A
        token_inserts = [
            c.args for c in cur.execute.call_args_list
            if "INSERT INTO oauth_tokens" in c.args[0]
        ]
        assert len(token_inserts) == 2
        for _sql, params in token_inserts:
            assert "user-A" in params


# ── /.well-known discovery is FROZEN — must be unchanged ────────────────────

class TestWellKnownUnchanged:
    @pytest.mark.anyio
    async def test_authorization_server_metadata(self):
        from private_internet.auth import routes
        fake = SimpleNamespace(base_url="https://app.example.com")
        with patch.object(routes, "get_settings", return_value=fake):
            doc = await routes.oauth_authorization_server()
        assert doc == {
            "issuer": "https://app.example.com",
            "authorization_endpoint": "https://app.example.com/api/oauth/authorize",
            "token_endpoint": "https://app.example.com/api/oauth/token",
            "registration_endpoint": "https://app.example.com/api/oauth/register",
            "code_challenge_methods_supported": ["S256"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }

    @pytest.mark.anyio
    async def test_protected_resource_metadata(self):
        from private_internet.auth import routes
        fake = SimpleNamespace(base_url="https://app.example.com")
        with patch.object(routes, "get_settings", return_value=fake):
            doc = await routes.get_well_known()
        assert doc == {
            "resource": "https://app.example.com",
            "authorization_servers": ["https://app.example.com"],
        }


# ── /authorize binds the logged-in platform user (opportunistic) ────────────

class TestAuthorizeBindsPlatformUser:
    def test_platform_user_id_decodes_jwt_subject(self):
        from private_internet.auth import routes
        with patch.object(routes, "decode_user_token", return_value={"sub": "user-A"}):
            assert routes._platform_user_id("a.jwt.token") == "user-A"

    def test_platform_user_id_none_for_bad_jwt(self):
        from private_internet.auth import routes
        with patch.object(routes, "decode_user_token", return_value=None):
            assert routes._platform_user_id("bad") is None

    def test_platform_user_id_none_for_missing(self):
        from private_internet.auth import routes
        assert routes._platform_user_id(None) is None
        assert routes._platform_user_id("") is None
