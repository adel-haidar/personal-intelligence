"""GitHub connector — imports README files from a user's repositories.

OAuth flow:
  authorize → https://github.com/login/oauth/authorize  (scope: repo read:user)
  token     → https://github.com/login/oauth/access_token

Fetch strategy:
  GET /user/repos  (all repos the token can see, paginated)
  GET /repos/{owner}/{repo}/readme  (Accept: application/vnd.github.raw)

GitHub classic OAuth access tokens do not expire (no refresh token).
Env vars required: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from private_internet.config import get_settings
from private_internet.connectors.base import Connector, Credentials, FetchPage, Item

logger = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_API_BASE = "https://api.github.com"
_PAGE_SIZE = 50
_SCOPE = "repo read:user"


def _redirect_uri() -> str:
    return f"{get_settings().base_url}/api/connectors/github/callback"


def _gh_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _json_get(url: str, headers: dict) -> dict | list:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _raw_get(url: str, headers: dict) -> str:
    req = urllib.request.Request(url, headers={**headers, "Accept": "application/vnd.github.raw"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


class GitHubConnector(Connector):
    id = "github"
    display_name = "GitHub"

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.github_client_id and s.github_client_secret)

    def authorize_url(self, state: str) -> str:
        s = get_settings()
        params = urllib.parse.urlencode({
            "client_id": s.github_client_id,
            "redirect_uri": _redirect_uri(),
            "scope": _SCOPE,
            "state": state,
        })
        return f"{_AUTHORIZE_URL}?{params}"

    def exchange_code(self, code: str) -> Credentials:
        s = get_settings()
        body = urllib.parse.urlencode({
            "client_id": s.github_client_id,
            "client_secret": s.github_client_secret,
            "code": code,
            "redirect_uri": _redirect_uri(),
        }).encode()
        req = urllib.request.Request(
            _TOKEN_URL,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if "error" in resp:
            raise ValueError(f"GitHub token exchange failed: {resp['error']}")
        access_token = resp["access_token"]
        # Fetch the authenticated user's login to store as external_account.
        try:
            user_info = _json_get(f"{_API_BASE}/user", _gh_headers(access_token))
            external_account = user_info.get("login")  # type: ignore[union-attr]
        except Exception:
            external_account = None
        return Credentials(
            access_token=access_token,
            # GitHub classic OAuth tokens do not expire and have no refresh token.
            refresh_token=None,
            expiry=None,
            scopes=resp.get("scope"),
            external_account=external_account,
        )

    def refresh(self, creds: Credentials) -> Credentials:
        raise NotImplementedError("GitHub classic OAuth tokens do not expire")

    def fetch_items(self, creds: Credentials, cursor: str | None = None) -> FetchPage:
        """Fetch repos page by page; cursor encodes the page number (1-based)."""
        headers = _gh_headers(creds.access_token)
        page = int(cursor) if cursor else 1
        url = f"{_API_BASE}/user/repos?per_page={_PAGE_SIZE}&page={page}&sort=updated&affiliation=owner,collaborator"
        try:
            repos = _json_get(url, headers)
        except Exception as exc:
            logger.warning("GitHub repos fetch failed (page %s): %s", page, exc)
            return FetchPage(items=[], next_cursor=None)

        if not isinstance(repos, list):
            return FetchPage(items=[], next_cursor=None)

        items: list[Item] = []
        for repo in repos:
            repo_full = repo.get("full_name", "")
            repo_name = repo.get("name", repo_full)
            description = repo.get("description") or ""
            html_url = repo.get("html_url")
            # Fetch the README content.
            readme_url = f"{_API_BASE}/repos/{repo_full}/readme"
            try:
                readme_text = _raw_get(readme_url, headers)
            except Exception:
                # Repo has no README or it's not accessible — use the description.
                readme_text = description
            content = readme_text.strip() or description or repo_name
            items.append(Item(
                external_id=str(repo.get("id", repo_full)),
                title=f"{repo_full} — README",
                content=content,
                source_url=html_url,
                modified_at=None,
            ))

        # If we got a full page there might be more; otherwise we're done.
        next_cursor = str(page + 1) if len(repos) == _PAGE_SIZE else None
        return FetchPage(items=items, next_cursor=next_cursor)
