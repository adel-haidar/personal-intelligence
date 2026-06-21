"""Connector registry.

Exposes:
  REAL_CONNECTORS   — live connector instances keyed by id
  COMING_SOON       — metadata tiles for platforms not yet implemented
  get_connector(id) — look up a Connector instance by id
  list_connector_meta(user_id) — full tile list for the dashboard
"""

from __future__ import annotations

from private_internet.connectors.base import Connector
from private_internet.connectors.providers.gdrive import GDriveConnector
from private_internet.connectors.providers.github import GitHubConnector
from private_internet.connectors.providers.notion import NotionConnector

# Concrete connectors (have a working OAuth + fetch implementation).
REAL_CONNECTORS: dict[str, Connector] = {
    c.id: c
    for c in [
        NotionConnector(),
        GitHubConnector(),
        GDriveConnector(),
    ]
}

# Platforms on the roadmap — shown as "coming soon" tiles with no interactive state.
COMING_SOON: list[dict] = [
    {"id": "claude",   "display_name": "Claude.ai"},
    {"id": "gmail",    "display_name": "Gmail"},
    {"id": "onedrive", "display_name": "OneDrive"},
    {"id": "meta",     "display_name": "Meta"},
    {"id": "x",        "display_name": "X (Twitter)"},
]

_COMING_SOON_IDS = {c["id"] for c in COMING_SOON}


def get_connector(connector_id: str) -> Connector | None:
    """Return a Connector instance, or None if the id is unknown or coming-soon."""
    return REAL_CONNECTORS.get(connector_id)


def list_connector_meta(user_id: str) -> list[dict]:
    """Return tile metadata for every connector (real + coming soon).

    DB fields (connected, status, last_sync_at, imported_count) are fetched
    from connector_accounts and connector_items for the calling user.
    """
    # Import here to avoid a circular dependency (db imports from registry
    # only indirectly via service).
    from private_internet.connectors.db import get_all_accounts, get_imported_counts

    accounts = get_all_accounts(user_id)          # {connector_id: account_row}
    imported_counts = get_imported_counts(user_id) # {connector_id: int}

    tiles: list[dict] = []

    for connector_id, connector in REAL_CONNECTORS.items():
        account = accounts.get(connector_id)
        connected = account is not None
        tiles.append({
            "id": connector_id,
            "display_name": connector.display_name,
            "coming_soon": False,
            "configured": connector.is_configured(),
            "connected": connected,
            "status": account["status"] if account else None,
            "last_sync_at": (
                account["last_sync_at"].isoformat() if account and account["last_sync_at"] else None
            ),
            "imported_count": imported_counts.get(connector_id, 0),
        })

    for cs in COMING_SOON:
        tiles.append({
            "id": cs["id"],
            "display_name": cs["display_name"],
            "coming_soon": True,
            "configured": False,
            "connected": False,
            "status": None,
            "last_sync_at": None,
            "imported_count": 0,
        })

    return tiles
