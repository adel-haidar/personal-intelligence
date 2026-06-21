"""Notion connector — imports pages and databases from a user's Notion workspace.

OAuth flow:
  authorize → https://api.notion.com/v1/oauth/authorize
  token     → https://api.notion.com/v1/oauth/token  (HTTP Basic auth)

Fetch strategy:
  POST /v1/search  (all pages, sorted by last_edited_time desc)
  GET  /v1/blocks/{id}/children  (flatten rich_text to plain text, recursively)

Env vars required: NOTION_CLIENT_ID, NOTION_CLIENT_SECRET.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from private_internet.config import get_settings
from private_internet.connectors.base import Connector, Credentials, FetchPage, Item

logger = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
_SEARCH_URL = "https://api.notion.com/v1/search"
_BLOCKS_URL = "https://api.notion.com/v1/blocks/{id}/children"
_NOTION_VERSION = "2022-06-28"
_PAGE_SIZE = 50


def _redirect_uri() -> str:
    return f"{get_settings().base_url}/api/connectors/notion/callback"


def _notion_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _json_request(url: str, method: str = "GET", headers: dict | None = None,
                  body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _rich_text_to_plain(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _extract_block_text(block: dict) -> str:
    """Extract the plain text from a single block's rich_text array."""
    btype = block.get("type", "")
    inner = block.get(btype, {})
    rich_text = inner.get("rich_text", [])
    return _rich_text_to_plain(rich_text)


def _fetch_block_children(block_id: str, access_token: str, depth: int = 0) -> str:
    """Recursively fetch and flatten all descendant blocks to plain text."""
    if depth > 3:
        # Guard against pathologically deep Notion page nesting.
        return ""
    headers = _notion_headers(access_token)
    lines: list[str] = []
    cursor = None
    while True:
        url = _BLOCKS_URL.format(id=block_id)
        if cursor:
            url += f"?start_cursor={cursor}"
        try:
            resp = _json_request(url, headers=headers)
        except Exception as exc:
            logger.warning("Notion block fetch failed for %s: %s", block_id, exc)
            break
        for block in resp.get("results", []):
            text = _extract_block_text(block)
            if text:
                lines.append(text)
            if block.get("has_children"):
                child_text = _fetch_block_children(block["id"], access_token, depth + 1)
                if child_text:
                    lines.append(child_text)
        cursor = resp.get("next_cursor")
        if not cursor:
            break
    return "\n".join(lines)


def _page_title(page: dict) -> str:
    props = page.get("properties", {})
    # Pages use "title" or "Name" as the title property key.
    for key in ("title", "Name"):
        prop = props.get(key, {})
        title_arr = prop.get("title", [])
        if title_arr:
            return _rich_text_to_plain(title_arr)
    # Fallback: first title-type property found.
    for prop in props.values():
        if prop.get("type") == "title":
            title_arr = prop.get("title", [])
            if title_arr:
                return _rich_text_to_plain(title_arr)
    return "(Untitled)"


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


class NotionConnector(Connector):
    id = "notion"
    display_name = "Notion"

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.notion_client_id and s.notion_client_secret)

    def authorize_url(self, state: str) -> str:
        s = get_settings()
        params = urllib.parse.urlencode({
            "client_id": s.notion_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "owner": "user",
            "state": state,
        })
        return f"{_AUTHORIZE_URL}?{params}"

    def exchange_code(self, code: str) -> Credentials:
        s = get_settings()
        # Notion requires HTTP Basic auth (client_id:client_secret).
        credentials_b64 = base64.b64encode(
            f"{s.notion_client_id}:{s.notion_client_secret}".encode()
        ).decode()
        body = json.dumps({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
        }).encode()
        req = urllib.request.Request(
            _TOKEN_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {credentials_b64}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        account = resp.get("workspace_name") or resp.get("owner", {}).get("user", {}).get("name")
        return Credentials(
            access_token=resp["access_token"],
            # Notion tokens do not expire and have no refresh token.
            refresh_token=None,
            expiry=None,
            scopes=None,
            external_account=account,
        )

    # Notion tokens do not expire → refresh is not needed.
    def refresh(self, creds: Credentials) -> Credentials:
        raise NotImplementedError("Notion tokens do not expire; refresh is not supported")

    def fetch_items(self, creds: Credentials, cursor: str | None = None) -> FetchPage:
        headers = _notion_headers(creds.access_token)
        body: dict = {
            "page_size": _PAGE_SIZE,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        if cursor:
            body["start_cursor"] = cursor

        resp = _json_request(_SEARCH_URL, method="POST", headers=headers, body=body)
        items: list[Item] = []
        for page in resp.get("results", []):
            page_id = page.get("id", "")
            obj_type = page.get("object", "")
            if obj_type not in ("page", "database"):
                continue
            title = _page_title(page)
            url = page.get("url")
            edited = _parse_dt(page.get("last_edited_time"))
            # Fetch body content from the page's block children.
            try:
                content = _fetch_block_children(page_id, creds.access_token)
            except Exception as exc:
                logger.warning("Notion page content fetch failed for %s: %s", page_id, exc)
                content = ""
            if not content.strip():
                content = title  # at minimum store the title so the embedding is non-empty
            items.append(Item(
                external_id=page_id,
                title=title,
                content=content,
                source_url=url,
                modified_at=edited,
            ))
        return FetchPage(
            items=items,
            next_cursor=resp.get("next_cursor"),
        )
