"""Google Drive connector — imports documents from the user's Drive.

OAuth flow:
  Reuses the same Google OAuth endpoints as users/google_auth.py:
  authorize → https://accounts.google.com/o/oauth2/v2/auth
  token     → https://oauth2.googleapis.com/token
  Reuses GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from config.

Scope:
  https://www.googleapis.com/auth/drive.readonly
  (drive.file is the lower-friction alternative — only files created by this app.
   drive.readonly is needed to read pre-existing documents.)

Fetch strategy:
  GET /drive/v3/files  (q: not trashed, mimeType in [text/*, application/vnd.google-apps.document])
  Google Docs → export as text/plain via /files/{id}/export?mimeType=text/plain
  Plain text files → download via /files/{id}?alt=media
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from private_internet.config import get_settings
from private_internet.connectors.base import Connector, Credentials, FetchPage, Item

logger = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_DRIVE_EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{id}/export"
_DRIVE_MEDIA_URL = "https://www.googleapis.com/drive/v3/files/{id}"

# drive.readonly allows reading all files.
# drive.file is the lower-friction alternative (only files created by this app).
_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

_PAGE_SIZE = 50
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/html",
}


def _redirect_uri() -> str:
    return f"{get_settings().base_url}/api/connectors/gdrive/callback"


def _bearer_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _json_get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _raw_get(url: str, headers: dict, max_bytes: int = 500_000) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(max_bytes).decode("utf-8", errors="replace")


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


class GDriveConnector(Connector):
    id = "gdrive"
    display_name = "Google Drive"

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.google_client_id and s.google_client_secret)

    def authorize_url(self, state: str) -> str:
        s = get_settings()
        params = urllib.parse.urlencode({
            "client_id": s.google_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",   # force refresh_token to be returned
            "state": state,
        })
        return f"{_AUTHORIZE_URL}?{params}"

    def exchange_code(self, code: str) -> Credentials:
        s = get_settings()
        body = urllib.parse.urlencode({
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        }).encode()
        req = urllib.request.Request(
            _TOKEN_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if "error" in resp:
            raise ValueError(f"Google Drive token exchange failed: {resp['error']}")
        expiry = None
        expires_in = resp.get("expires_in")
        if expires_in:
            from datetime import timedelta
            expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        # Fetch the account email to store as external_account.
        access_token = resp["access_token"]
        try:
            userinfo = _json_get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                _bearer_headers(access_token),
            )
            external_account = userinfo.get("email")
        except Exception:
            external_account = None
        return Credentials(
            access_token=access_token,
            refresh_token=resp.get("refresh_token"),
            expiry=expiry,
            scopes=resp.get("scope"),
            external_account=external_account,
        )

    def refresh(self, creds: Credentials) -> Credentials:
        if not creds.refresh_token:
            raise ValueError("No refresh token available for Google Drive")
        s = get_settings()
        body = urllib.parse.urlencode({
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "refresh_token": creds.refresh_token,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            _TOKEN_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if "error" in resp:
            raise ValueError(f"Google Drive token refresh failed: {resp['error']}")
        from datetime import timedelta
        expires_in = resp.get("expires_in", 3600)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        return Credentials(
            access_token=resp["access_token"],
            refresh_token=creds.refresh_token,  # Google reuses the same refresh token
            expiry=expiry,
            scopes=resp.get("scope", creds.scopes),
            external_account=creds.external_account,
        )

    def fetch_items(self, creds: Credentials, cursor: str | None = None) -> FetchPage:
        headers = _bearer_headers(creds.access_token)
        # List text files and Google Docs (not trashed).
        params: dict = {
            "pageSize": str(_PAGE_SIZE),
            "q": "trashed = false and (mimeType = 'application/vnd.google-apps.document' or mimeType contains 'text/')",
            "fields": "nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime)",
            "orderBy": "modifiedTime desc",
        }
        if cursor:
            params["pageToken"] = cursor
        url = f"{_DRIVE_FILES_URL}?{urllib.parse.urlencode(params)}"
        try:
            resp = _json_get(url, headers)
        except Exception as exc:
            logger.warning("Google Drive file list failed: %s", exc)
            return FetchPage(items=[], next_cursor=None)

        items: list[Item] = []
        for f in resp.get("files", []):
            file_id = f.get("id", "")
            name = f.get("name", "(Untitled)")
            mime = f.get("mimeType", "")
            web_url = f.get("webViewLink")
            modified_at = _parse_dt(f.get("modifiedTime"))
            try:
                if mime == _GOOGLE_DOC_MIME:
                    export_url = f"{_DRIVE_EXPORT_URL.format(id=file_id)}?mimeType=text/plain"
                    content = _raw_get(export_url, headers)
                elif mime in _TEXT_MIMES or mime.startswith("text/"):
                    media_url = f"{_DRIVE_MEDIA_URL.format(id=file_id)}?alt=media"
                    content = _raw_get(media_url, headers)
                else:
                    # mimeType matched the text/ contains filter but we don't handle it
                    continue
            except Exception as exc:
                logger.warning("Google Drive content fetch failed for %s (%s): %s", file_id, name, exc)
                content = name  # store the title at minimum
            if not content.strip():
                content = name
            items.append(Item(
                external_id=file_id,
                title=name,
                content=content,
                source_url=web_url,
                modified_at=modified_at,
            ))

        return FetchPage(
            items=items,
            next_cursor=resp.get("nextPageToken"),
        )
