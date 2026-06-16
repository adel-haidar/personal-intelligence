import secrets
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from private_internet.database import _connect


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def generate_client_secret() -> str:
    return secrets.token_urlsafe(32)


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == code_challenge


def create_oauth_tables():
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS oauth_clients (
            client_id TEXT PRIMARY KEY,
            client_secret TEXT,
            redirect_uris TEXT[] NOT NULL,
            client_name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS oauth_codes (
            code TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            code_challenge_method TEXT DEFAULT 'S256',
            redirect_uri TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            token TEXT PRIMARY KEY,
            token_type TEXT NOT NULL,
            client_id TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            refresh_token TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    # 0016: bind authorizations/tokens to the platform user who authorized them.
    # Columns only here (no FK) — the `users` table is created later in the
    # startup order (multi-tenancy migration). The FK + backfill is applied by
    # bootstrap_oauth_user_binding() after `users` exists.
    cur.execute("ALTER TABLE oauth_codes  ADD COLUMN IF NOT EXISTS user_id UUID")
    cur.execute("ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS user_id UUID")
    conn.commit()
    cur.close()
    conn.close()


def bootstrap_oauth_user_binding() -> None:
    """Mirror of migrations/0016_oauth_user_binding.sql — add the FK to
    users(id) and backfill legacy (user_id IS NULL) rows to the seed admin so
    already-connected claude.ai sessions keep resolving to the owner's brain
    until they re-authorize. Idempotent; must run AFTER the `users` table exists.
    """
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass('public.users')")
        if cur.fetchone()[0] is None:
            return  # users table not created yet — nothing to bind to

        cur.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'oauth_codes_user_id_fkey'"
        )
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE oauth_codes ADD CONSTRAINT oauth_codes_user_id_fkey "
                "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            )
        cur.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'oauth_tokens_user_id_fkey'"
        )
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE oauth_tokens ADD CONSTRAINT oauth_tokens_user_id_fkey "
                "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            )

        cur.execute(
            "UPDATE oauth_codes c SET user_id = a.id "
            "FROM (SELECT id FROM users WHERE is_admin = TRUE "
            "      ORDER BY created_at LIMIT 1) a "
            "WHERE c.user_id IS NULL"
        )
        cur.execute(
            "UPDATE oauth_tokens t SET user_id = a.id "
            "FROM (SELECT id FROM users WHERE is_admin = TRUE "
            "      ORDER BY created_at LIMIT 1) a "
            "WHERE t.user_id IS NULL"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_oauth_tokens_user_id "
            "ON oauth_tokens(user_id)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def register_client(client_name: str, redirect_uris: list[str]) -> dict:
    client_id = secrets.token_urlsafe(16)
    client_secret = generate_client_secret()
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oauth_clients (client_id, client_secret, redirect_uris, client_name) VALUES (%s, %s, %s, %s)",
        (client_id, client_secret, redirect_uris, client_name),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"client_id": client_id, "client_secret": client_secret}


def create_auth_code(
    client_id: str,
    code_challenge: str,
    redirect_uri: str,
    user_id: str | None = None,
) -> str:
    """Issue an authorization code.

    ``user_id`` binds the code (and, after exchange, the resulting tokens) to the
    platform user who authorized at the consent screen. When None (e.g. the
    legacy dashboard-password gate authorized without a platform JWT), the code
    is left unbound; token resolution then falls back to the seed admin.
    """
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oauth_codes (code, client_id, code_challenge, redirect_uri, expires_at, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (code, client_id, code_challenge, redirect_uri, expires_at, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return code


def exchange_code(code: str, code_verifier: str, client_id: str) -> dict | None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT code_challenge, redirect_uri, expires_at, used, user_id FROM oauth_codes WHERE code = %s AND client_id = %s",
        (code, client_id),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None

    code_challenge, redirect_uri, expires_at, used, user_id = row

    if used or datetime.now(timezone.utc) > expires_at:
        cur.close()
        conn.close()
        return None

    if not verify_pkce(code_verifier, code_challenge):
        cur.close()
        conn.close()
        return None

    cur.execute("UPDATE oauth_codes SET used = TRUE WHERE code = %s", (code,))

    access_token = generate_token()
    refresh_token = generate_token()
    access_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=90)

    # Propagate the platform user binding from the authorization code onto both
    # the access and refresh tokens, so the MCP server can resolve the real user.
    cur.execute(
        "INSERT INTO oauth_tokens (token, token_type, client_id, expires_at, refresh_token, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (access_token, "access", client_id, access_expires, refresh_token, user_id),
    )
    cur.execute(
        "INSERT INTO oauth_tokens (token, token_type, client_id, expires_at, user_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (refresh_token, "refresh", client_id, refresh_expires, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh_token,
    }


def refresh_access_token(refresh_token: str, client_id: str) -> dict | None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT expires_at, user_id FROM oauth_tokens WHERE token = %s AND token_type = 'refresh' AND client_id = %s",
        (refresh_token, client_id),
    )
    row = cur.fetchone()
    if not row or datetime.now(timezone.utc) > row[0]:
        cur.close()
        conn.close()
        return None

    user_id = row[1]
    access_token = generate_token()
    access_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    cur.execute(
        "INSERT INTO oauth_tokens (token, token_type, client_id, expires_at, refresh_token, user_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (access_token, "access", client_id, access_expires, refresh_token, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": refresh_token,
    }


def validate_token(token: str) -> str | None:
    """Returns client_id if the access token is valid, None otherwise.

    Unchanged behavior — kept for callers that only need to verify validity /
    read the client_id (nginx auth_request, RequestContext legacy fallback).
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT client_id, expires_at FROM oauth_tokens WHERE token = %s AND token_type = 'access'",
        (token,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or datetime.now(timezone.utc) > row[1]:
        return None
    return row[0]


def resolve_token_user(token: str) -> str | None:
    """Return the platform user_id bound to a valid access token.

    Returns None if the token is invalid/expired OR is valid but unbound (a
    legacy token issued before user binding existed, or authorized via the
    dashboard-password gate without a platform JWT). Callers fall back to the
    seed admin on None so already-connected claude.ai sessions keep working.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, expires_at FROM oauth_tokens WHERE token = %s AND token_type = 'access'",
        (token,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or datetime.now(timezone.utc) > row[1]:
        return None
    return str(row[0]) if row[0] is not None else None
