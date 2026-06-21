"""Connector abstraction layer.

Each external platform (Notion, GitHub, Google Drive, …) is a Connector subclass.
The ABC defines the interface every provider must implement; orchestration lives in
service.py and the REST layer in routes.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Credentials:
    """OAuth tokens for one connected account."""
    access_token: str
    refresh_token: str | None = None
    expiry: datetime | None = None
    scopes: str | None = None
    # Human-readable account label (e.g. "adel@gmail.com" or GitHub username).
    external_account: str | None = None


@dataclass
class Item:
    """A single importable document/message from the external platform."""
    external_id: str          # provider-unique identifier for deduplication
    title: str
    content: str              # plain-text content to embed
    source_url: str | None = None
    modified_at: datetime | None = None
    # When the item is a real file (e.g. a CV PDF in Google Drive), the provider
    # may supply the original bytes + filename. The import pipeline then persists
    # the binary to the user's upload dir and tags the memory `file-upload`, so
    # downstream consumers that need the original file — notably the job-hunt
    # agent merging a CV into an application — can find and attach it, exactly as
    # if it had been uploaded via POST /api/file. Leave None for text-only items
    # (Notion pages, GitHub READMEs).
    raw_bytes: bytes | None = None
    filename: str | None = None   # original filename incl. extension


@dataclass
class FetchPage:
    """One page of items returned by fetch_items."""
    items: list[Item] = field(default_factory=list)
    next_cursor: str | None = None   # None = last page


class Connector(ABC):
    """Base class for external platform connectors.

    Subclasses must set `id` (slug), `display_name`, and optionally override
    `coming_soon` (default False). The orchestrator in service.py calls these
    methods in order: is_configured → authorize_url → exchange_code →
    fetch_items (in a loop until next_cursor is None).
    """

    # Concrete subclasses set these as class attributes.
    id: str = ""
    display_name: str = ""
    coming_soon: bool = False

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True only when the required env vars / settings are present."""

    @abstractmethod
    def authorize_url(self, state: str) -> str:
        """Build the provider OAuth authorization URL with the given state."""

    @abstractmethod
    def exchange_code(self, code: str) -> Credentials:
        """Exchange an authorization code for credentials."""

    def refresh(self, creds: Credentials) -> Credentials:
        """Obtain a fresh access token using the refresh token.

        Providers that issue non-expiring tokens (e.g. GitHub classic PAT) or
        do not support refresh may raise NotImplementedError.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support token refresh")

    @abstractmethod
    def fetch_items(self, creds: Credentials, cursor: str | None = None) -> FetchPage:
        """Fetch one page of items. Pass cursor=None for the first page."""
