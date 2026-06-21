from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Platform(BaseModel):
    """One job board available for a country. `platform_key` is a stable slug
    (e.g. 'jobs_ch'); `domain`/`display_name` are what we match JSearch's
    `job_publisher` against when filtering a search to the user's selection."""

    country_code: str
    platform_key: str
    display_name: str
    domain: Optional[str] = None
    source_kind: str = "jsearch"          # 'jsearch' | 'adapter'
    adapter_host: Optional[str] = None
    rank: int = 0
    available: bool = True                 # confirmed by live JSearch sampling
    needs_key: bool = False                # a dedicated source needs a key we lack
    last_checked: Optional[datetime] = None


class CountryDiscovery(BaseModel):
    """Result of discovering platforms for a single country (one worker)."""

    country_code: str
    platforms: list[Platform] = []
    validated: bool = False                # True if a live JSearch sample ran
    error: Optional[str] = None            # set when the worker hit a key/quota issue


class DiscoveryReport(BaseModel):
    """Aggregated outcome of an orchestration pass over many countries."""

    countries: list[str] = []
    total_platforms: int = 0
    validated_countries: int = 0
    needs_key: bool = False                # any platform requires a key we don't have
    key_errors: list[str] = []             # distinct RapidAPI key/quota reasons seen
    ran_at: datetime
