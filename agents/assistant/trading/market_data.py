"""Web market-data fetcher for the day-trading adviser.

Pulls a same-day snapshot of index quotes and financial headlines that is fed
to the LLM as ground truth — the Bedrock model cannot browse, so everything it
'fetches from the web' is collected here server-side.

Sources:
  - Yahoo Finance      — index/stock quotes (public chart API) + news RSS
  - Bloomberg          — markets news RSS
  - The Economist      — finance & economics RSS
  - Google Finance     — headlines via Google News RSS (Google Finance itself
                         has no public feed)
  - Koyfin             — NO public API or feed; listed for transparency in
                         sources_failed so the analysis is honest about it.

Every fetch is best-effort with a short timeout: a dead feed degrades the
snapshot, it never breaks the analysis.
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) adel-intelligence/1.0"}
_TIMEOUT = httpx.Timeout(10.0)

# Region → [(Yahoo symbol, display name)]
INDICES: dict[str, list[tuple[str, str]]] = {
    "us": [
        ("^GSPC", "S&P 500"),
        ("^IXIC", "Nasdaq Composite"),
        ("^DJI",  "Dow Jones Industrial Average"),
    ],
    "europe": [
        ("^GDAXI",    "DAX (Germany)"),
        ("^STOXX50E", "Euro Stoxx 50"),
        ("^FTSE",     "FTSE 100 (UK)"),
    ],
    "southeast_asia": [
        ("^STI",  "Straits Times Index (Singapore)"),
        ("^JKSE", "IDX Composite (Indonesia)"),
        ("^KLSE", "FTSE Bursa Malaysia KLCI"),
        ("^SET.BK", "SET Index (Thailand)"),
    ],
}

NEWS_FEEDS: list[tuple[str, str]] = [
    ("Yahoo Finance",  "https://finance.yahoo.com/news/rssindex"),
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("The Economist (Finance & economics)", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("Google Finance (via Google News)",
     "https://news.google.com/rss/search?q=stock+market+when:1d&hl=en-US&gl=US&ceid=US:en"),
]

_HEADLINES_PER_FEED = 8


async def _fetch_quote(client: httpx.AsyncClient, symbol: str, name: str) -> dict | None:
    """Fetch the latest price + day change for a symbol from Yahoo's chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        resp = await client.get(url, params={"range": "5d", "interval": "1d"})
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None:
            return None
        change_pct = ((price / prev) - 1) * 100 if prev else None
        return {
            "symbol":     symbol,
            "name":       name,
            "price":      round(price, 2),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "currency":   meta.get("currency"),
        }
    except Exception:
        logger.warning("Quote fetch failed for %s", symbol, exc_info=True)
        return None


async def _fetch_headlines(client: httpx.AsyncClient, source: str, url: str) -> list[str] | None:
    """Fetch RSS/Atom headline titles from a news feed."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        # RSS: channel/item/title; Atom: {ns}entry/{ns}title
        atom = "{http://www.w3.org/2005/Atom}"
        title_els = root.findall(".//item/title") or root.findall(f".//{atom}entry/{atom}title")
        titles = [el.text.strip() for el in title_els if el.text and el.text.strip()]
        return titles[:_HEADLINES_PER_FEED]
    except Exception:
        logger.warning("Headline fetch failed for %s", source, exc_info=True)
        return None


async def collect_market_snapshot(watchlist: list[str] | None = None) -> dict:
    """Collect quotes for all regional indices + watchlist and recent headlines.

    Args:
        watchlist: Extra Yahoo symbols to quote (e.g. tickers recommended in the
            previous analysis, so the model can follow up on its own calls).

    Returns:
        A JSON-serialisable snapshot dict with indices per region, watchlist
        quotes, headlines per source, and source health for transparency.
    """
    watchlist = [s for s in dict.fromkeys(watchlist or []) if s]

    async with httpx.AsyncClient(headers=_UA, timeout=_TIMEOUT, follow_redirects=True) as client:
        index_jobs = [
            (region, _fetch_quote(client, symbol, name))
            for region, pairs in INDICES.items()
            for symbol, name in pairs
        ]
        watch_jobs = [_fetch_quote(client, s, s) for s in watchlist]
        news_jobs  = [_fetch_headlines(client, source, url) for source, url in NEWS_FEEDS]

        results = await asyncio.gather(
            *(job for _, job in index_jobs), *watch_jobs, *news_jobs,
        )

    n_idx, n_watch = len(index_jobs), len(watch_jobs)
    index_results = results[:n_idx]
    watch_results = results[n_idx:n_idx + n_watch]
    news_results  = results[n_idx + n_watch:]

    indices: dict[str, list[dict]] = {region: [] for region in INDICES}
    for (region, _), quote in zip(index_jobs, index_results):
        if quote:
            indices[region].append(quote)

    headlines: dict[str, list[str]] = {}
    sources_ok:     list[str] = []
    sources_failed: list[str] = ["Koyfin (no public API/feed)"]
    for (source, _), titles in zip(NEWS_FEEDS, news_results):
        if titles:
            headlines[source] = titles
            sources_ok.append(source)
        else:
            sources_failed.append(source)
    if any(indices.values()):
        sources_ok.insert(0, "Yahoo Finance quotes")
    else:
        sources_failed.insert(0, "Yahoo Finance quotes")

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "indices":    indices,
        "watchlist":  [q for q in watch_results if q],
        "headlines":  headlines,
        "sources_ok": sources_ok,
        "sources_failed": sources_failed,
    }
