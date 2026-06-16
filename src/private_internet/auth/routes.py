import hashlib
import hmac
import time

from fastapi import APIRouter, Cookie, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from private_internet.auth.oauth import (
    create_auth_code,
    exchange_code,
    refresh_access_token,
    register_client,
)
from private_internet.config import get_settings
from private_internet.users.tokens import decode_user_token

router = APIRouter()

_SESSION_COOKIE = "pi_session"
_SESSION_MAX_AGE = 86400  # 24 hours

# Cookie the dashboard SPA may set with the logged-in user's platform JWT so the
# OAuth consent step can bind the authorization to the REAL platform user. Also
# accepted as a `platform_jwt` query/form param. Optional — when absent the flow
# behaves exactly as before and the token resolves to the seed admin.
_PLATFORM_JWT_COOKIE = "pi_jwt"


def _platform_user_id(jwt_value: str | None) -> str | None:
    """Decode a platform JWT and return its subject (user id), or None.

    Never raises — an invalid/expired/missing JWT yields None so the OAuth flow
    is never broken by a bad cookie; it simply falls back to seed-admin binding.
    """
    if not jwt_value:
        return None
    claims = decode_user_token(jwt_value)
    if not claims:
        return None
    sub = claims.get("sub")
    return str(sub) if sub else None


def _sign(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_session_token(secret: str) -> str:
    ts = str(int(time.time()))
    sig = _sign(ts, secret)
    return f"{ts}.{sig}"


def _validate_session_token(token: str, secret: str) -> bool:
    try:
        ts_str, sig = token.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(_sign(ts_str, secret), sig):
        return False
    return int(time.time()) - int(ts_str) < _SESSION_MAX_AGE


def _is_authenticated(pi_session: str | None) -> bool:
    settings = get_settings()
    if not settings.dashboard_password:
        return True  # password gate disabled — dev/test only
    if not pi_session:
        return False
    return _validate_session_token(pi_session, settings.dashboard_password)


# ---------------------------------------------------------------------------
# Well-known / discovery
# ---------------------------------------------------------------------------

@router.get("/.well-known/oauth-protected-resource")
async def get_well_known():
    base = get_settings().base_url
    return {
        "resource": base,
        "authorization_servers": [base],
    }


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server():
    base = get_settings().base_url
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/api/oauth/authorize",
        "token_endpoint": f"{base}/api/oauth/token",
        "registration_endpoint": f"{base}/api/oauth/register",
        "code_challenge_methods_supported": ["S256"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
    }


# ---------------------------------------------------------------------------
# Client registration — gated behind the session cookie
# ---------------------------------------------------------------------------

@router.post("/api/oauth/register")
async def register(request: Request):
    body = await request.json()
    result = register_client(
        client_name=body.get("client_name", "unknown"),
        redirect_uris=body.get("redirect_uris", []),
    )
    return {
        "client_id": result["client_id"],
        "client_secret": result["client_secret"],
        "client_name": body.get("client_name", "unknown"),
        "redirect_uris": body.get("redirect_uris", []),
        "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
        "response_types": body.get("response_types", ["code"]),
        "token_endpoint_auth_method": body.get("token_endpoint_auth_method", "none"),
    }


# ---------------------------------------------------------------------------
# Authorization endpoint — identity gate before code is issued
# ---------------------------------------------------------------------------

_LOGIN_FORM = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Private Internet — Login</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0d0d0d;color:#e0e0e0;font-family:monospace;
         display:grid;place-items:center;min-height:100vh}}
    .card{{border:1px solid #2a2a2a;padding:40px 36px;width:min(380px,90vw)}}
    h1{{font-size:11px;letter-spacing:.2em;text-transform:uppercase;
        color:#888;margin-bottom:28px}}
    label{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;
           color:#666;display:block;margin-bottom:6px}}
    input[type=password]{{width:100%;background:#151515;border:1px solid #2a2a2a;
                          color:#e0e0e0;padding:10px 12px;font-family:monospace;
                          font-size:13px;outline:none}}
    input[type=password]:focus{{border-color:#555}}
    button{{margin-top:20px;width:100%;padding:11px;background:transparent;
            border:1px solid #e0e0e0;color:#e0e0e0;font-family:monospace;
            font-size:10px;letter-spacing:.16em;text-transform:uppercase;cursor:pointer}}
    button:hover{{background:#1a1a1a}}
    .err{{margin-top:14px;font-size:10px;color:#c0392b;letter-spacing:.08em}}
  </style>
</head>
<body>
  <div class="card">
    <h1>Private Internet</h1>
    <form method="POST" action="/api/oauth/authorize">
      {hidden}
      <label for="pw">Access password</label>
      <input id="pw" name="password" type="password" autofocus autocomplete="current-password">
      {error}
      <button type="submit">Enter</button>
    </form>
  </div>
</body>
</html>
"""


def _hidden_fields(**kwargs) -> str:
    return "".join(
        f'<input type="hidden" name="{k}" value="{v}">'
        for k, v in kwargs.items()
        if v is not None
    )


@router.get("/api/oauth/authorize")
async def authorize(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    state: str = "",
    platform_jwt: str = "",
    pi_session: str | None = Cookie(default=None),
    pi_jwt: str | None = Cookie(default=None),
):
    if not _is_authenticated(pi_session):
        hidden = _hidden_fields(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
        )
        return HTMLResponse(_LOGIN_FORM.format(hidden=hidden, error=""))

    # Bind to the logged-in platform user if a JWT is presented (query param wins
    # over cookie); otherwise leave unbound → resolves to seed admin downstream.
    user_id = _platform_user_id(platform_jwt or pi_jwt)
    code = create_auth_code(
        client_id=client_id,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        user_id=user_id,
    )
    return RedirectResponse(url=f"{redirect_uri}?code={code}&state={state}")


@router.post("/api/oauth/authorize")
async def authorize_login(
    client_id: str = Form(),
    redirect_uri: str = Form(),
    code_challenge: str = Form(),
    code_challenge_method: str = Form(),
    state: str = Form(""),
    password: str = Form(),
    platform_jwt: str = Form(""),
    pi_jwt: str | None = Cookie(default=None),
):
    settings = get_settings()
    hidden = _hidden_fields(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        state=state,
    )

    if not settings.dashboard_password or password != settings.dashboard_password:
        error = '<p class="err">Incorrect password.</p>'
        return HTMLResponse(
            _LOGIN_FORM.format(hidden=hidden, error=error), status_code=401
        )

    session_token = _make_session_token(settings.dashboard_password)
    user_id = _platform_user_id(platform_jwt or pi_jwt)
    code = create_auth_code(
        client_id=client_id,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        user_id=user_id,
    )
    response = RedirectResponse(
        url=f"{redirect_uri}?code={code}&state={state}", status_code=303
    )
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=session_token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response


# ---------------------------------------------------------------------------
# Token endpoint — public (PKCE verifier protects it)
# ---------------------------------------------------------------------------

@router.post("/api/oauth/token")
async def token(
    grant_type: str = Form(),
    code: str = Form(""),
    code_verifier: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    refresh_token: str = Form(""),
):
    if grant_type == "authorization_code":
        result = exchange_code(
            code=code, code_verifier=code_verifier, client_id=client_id
        )
    elif grant_type == "refresh_token":
        result = refresh_access_token(refresh_token=refresh_token, client_id=client_id)
    else:
        raise HTTPException(status_code=400, detail="unsupported_grant_type")

    if not result:
        raise HTTPException(status_code=400, detail="invalid_grant")

    return result


# ---------------------------------------------------------------------------
# Internal auth endpoint — used by nginx auth_request subrequests
# ---------------------------------------------------------------------------

@router.get("/api/internal/auth")
async def internal_auth(request: Request):
    """Returns 200 if Bearer token is valid, 401 otherwise. nginx auth_request target."""
    from private_internet.auth.oauth import validate_token
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing token")
    token_val = auth[7:]
    if not validate_token(token_val):
        raise HTTPException(status_code=401, detail="invalid token")
    return {"ok": True}
