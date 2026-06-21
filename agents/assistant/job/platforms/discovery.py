"""Hub-and-spoke discovery orchestrator for per-country job platforms.

The **hub** (`orchestrate`) plans over a list of countries and fans out one
**worker** (`discover_country`) per country under a bounded semaphore. Each
worker:

  1. asks the LLM (Bedrock, temp=0) for the top job boards in that country, then
  2. runs one live JSearch sample and keeps only the boards JSearch can actually
     return (plus any real publishers the LLM didn't mention).

The hub aggregates the workers, ranks + persists them via `catalog`, and — if a
worker hit a RapidAPI key/quota failure so validation was impossible — invokes
the `fallback` strategy (LLM-only seeding so the dropdown is never empty) and
flags that human input is needed (the setup-guide endpoint explains the fix).
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from assistant.job.countries import name_for
from assistant.job.platforms import catalog
from assistant.job.platforms.models import (
    CountryDiscovery,
    DiscoveryReport,
    Platform,
)
from assistant.job.scrapers.base import ScraperError

logger = logging.getLogger(__name__)

# A common, market-agnostic role that surfaces a representative spread of
# publishers in every country with a single JSearch call (quota-friendly).
_SAMPLE_QUERY = "manager"

_PROPOSE_PROMPT = """\
You are a job-search expert. List the best job-search platforms (job boards) for \
finding jobs in {country}. Include the dominant international boards (e.g. \
LinkedIn, Indeed) AND the strongest local/regional boards for that country.

Rules:
- Return 4 to 8 platforms, best/most-used first.
- Return ONLY a valid JSON array, no prose. Each item: {{"name": "...", "domain": "..."}}
- "domain" is the platform's primary website domain (e.g. "jobs.ch", "linkedin.com").
- Do not invent platforms; only well-known, real job boards.

Example for Switzerland:
[{{"name":"LinkedIn","domain":"linkedin.com"}},{{"name":"jobs.ch","domain":"jobs.ch"}},{{"name":"Indeed","domain":"indeed.com"}}]

Return the JSON array for {country} now:"""


def slugify(value: str) -> str:
    """A stable platform_key from a name/domain: 'jobs.ch' → 'jobs_ch'."""
    s = re.sub(r"^www\.", "", (value or "").strip().lower())
    s = re.sub(r"\.(com|org|net|io|co|ch|de|jp|ca|fr|uk|nl)$", "", s)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "platform"


def _norm_domain(domain: Optional[str]) -> str:
    if not domain:
        return ""
    d = domain.strip().lower()
    if "://" in d:
        d = urlparse(d).netloc or d
    return re.sub(r"^www\.", "", d)


def _propose_platforms(bedrock_client, model_id: str, code: str) -> list[dict]:
    """LLM proposal of boards for a country. Returns [{name, domain}]; [] on failure."""
    prompt = _PROPOSE_PROMPT.format(country=name_for(code))
    try:
        response = bedrock_client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 512, "temperature": 0},
        )
        raw = response["output"]["message"]["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end <= start:
            return []
        items = json.loads(raw[start : end + 1])
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("name"):
                out.append({"name": str(it["name"]).strip(), "domain": _norm_domain(it.get("domain"))})
        return out
    except Exception:
        logger.warning("LLM platform proposal failed for %s", code, exc_info=True)
        return []


async def _sample_publishers(
    rapidapi_key: str, host: str, code: str
) -> list[tuple[str, str]]:
    """One live JSearch call; return (publisher_name, publisher_domain) pairs seen.

    Raises ScraperError on a key/quota failure so the orchestrator can route to
    the fallback strategy instead of silently treating the country as empty.
    """
    headers = {"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": host}
    params = {
        "query": _SAMPLE_QUERY,
        "num_pages": "1",
        "country": code.lower(),
        "employment_types": "FULLTIME",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"https://{host}/search", headers=headers, params=params)
            r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429:
            raise ScraperError("JSearch/RapidAPI quota exhausted or rate-limited (HTTP 429)") from exc
        if status in (401, 403):
            raise ScraperError(f"JSearch/RapidAPI rejected the API key (HTTP {status})") from exc
        raise ScraperError(f"JSearch/RapidAPI returned HTTP {status}") from exc
    except Exception as exc:
        raise ScraperError(f"JSearch/RapidAPI request failed: {exc}") from exc

    # Keep the first-seen original casing per publisher, plus a domain if we can
    # derive one from the apply link.
    seen: dict[str, tuple[str, str]] = {}
    for item in data.get("data") or []:
        publishers: list[str] = []
        if item.get("job_publisher"):
            publishers.append(item["job_publisher"])
        for opt in item.get("apply_options") or []:
            if opt.get("publisher"):
                publishers.append(opt["publisher"])
        link = item.get("job_apply_link") or ""
        link_domain = _norm_domain(urlparse(link).netloc) if link else ""
        for pub in publishers:
            key = pub.strip().lower()
            if key and key not in seen:
                seen[key] = (pub.strip(), link_domain)
    return list(seen.values())


def _build_platforms(
    code: str,
    proposed: list[dict],
    sampled: list[tuple[str, str]],
    *,
    validated: bool,
) -> list[Platform]:
    """Merge LLM proposals with live-sampled publishers into ranked Platform rows.

    - A proposed board confirmed in the sample → available, top ranks (LLM order).
    - A sampled publisher the LLM didn't name → available, mid rank.
    - A proposed board NOT seen in the sample → kept but available=False, low rank
      (so the UI can show it greyed rather than hiding it entirely).
    When validation didn't run (no sample), all proposals are kept as available
    on trust (the fallback path handles the no-key case separately).
    """
    sampled_names = {n.strip().lower(): (n, d) for n, d in sampled}
    sampled_domains = {_norm_domain(d): n for n, d in sampled if d}

    by_key: dict[str, Platform] = {}

    def _matches_sample(name: str, domain: str) -> bool:
        if name.strip().lower() in sampled_names:
            return True
        nd = _norm_domain(domain)
        return bool(nd) and nd in sampled_domains

    # Proposed boards, in LLM priority order.
    for i, item in enumerate(proposed):
        name, domain = item["name"], item.get("domain") or ""
        key = slugify(domain or name)
        confirmed = (not validated) or _matches_sample(name, domain)
        by_key[key] = Platform(
            country_code=code.upper(),
            platform_key=key,
            display_name=name,
            domain=_norm_domain(domain) or None,
            rank=(100 - i) if confirmed else (15 - i),
            available=confirmed,
        )

    # Extra real publishers the LLM didn't mention (only when we actually sampled).
    if validated:
        for name, domain in sampled:
            key = slugify(domain or name)
            if key in by_key:
                continue
            by_key[key] = Platform(
                country_code=code.upper(),
                platform_key=key,
                display_name=name,
                domain=_norm_domain(domain) or None,
                rank=50,
                available=True,
            )
    return list(by_key.values())


async def discover_country(
    bedrock_client,
    model_id: str,
    rapidapi_key: Optional[str],
    rapidapi_host: str,
    code: str,
) -> CountryDiscovery:
    """One discovery worker for a single country (runs the LLM + a live sample)."""
    loop = asyncio.get_event_loop()
    proposed = await loop.run_in_executor(
        None, _propose_platforms, bedrock_client, model_id, code
    )

    validated = False
    error: Optional[str] = None
    sampled: list[tuple[str, str]] = []
    if rapidapi_key:
        try:
            sampled = await _sample_publishers(rapidapi_key, rapidapi_host, code)
            validated = True
        except ScraperError as exc:
            error = str(exc)
            logger.warning("Discovery sample failed for %s: %s", code, exc)
    else:
        error = "RAPIDAPI_KEY is not set"

    platforms = _build_platforms(code, proposed, sampled, validated=validated)
    return CountryDiscovery(
        country_code=code.upper(), platforms=platforms, validated=validated, error=error
    )


async def orchestrate(
    database_url: str,
    bedrock_client,
    model_id: str,
    rapidapi_key: Optional[str],
    rapidapi_host: str,
    countries: list[str],
    *,
    concurrency: int = 4,
    fresh_within_hours: int = 24,
) -> DiscoveryReport:
    """Plan → fan out workers → aggregate → persist → fallback on key failure."""
    pool = await catalog.init_pool(database_url)

    all_codes = [c.upper() for c in countries if c]
    # Skip countries already validated within the freshness window (quota-friendly).
    codes = await catalog.stale_country_codes(pool, all_codes, fresh_within_hours)
    skipped = len(all_codes) - len(codes)
    logger.info(
        "Discovery plan: %d countries, %d stale to refresh, %d fresh-skipped",
        len(all_codes), len(codes), skipped,
    )

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run(code: str) -> CountryDiscovery:
        async with sem:
            return await discover_country(
                bedrock_client, model_id, rapidapi_key, rapidapi_host, code
            )

    discoveries = await asyncio.gather(*(_run(c) for c in codes)) if codes else []

    total_written = 0
    validated_countries = 0
    key_errors: list[str] = []
    for d in discoveries:
        if d.validated:
            validated_countries += 1
        elif d.error:
            key_errors.append(d.error)
        if d.platforms:
            total_written += await catalog.upsert_platforms(pool, d.platforms)

    needs_key = False
    # If NO country could be validated and we saw key/quota errors, validation is
    # systemically broken (bad/missing key) — seed via the fallback strategy and
    # signal that human input is needed.
    if codes and validated_countries == 0 and key_errors:
        # Imported lazily to avoid a circular import (fallback reuses helpers here).
        from assistant.job.platforms import fallback

        reason = "; ".join(dict.fromkeys(key_errors))
        logger.warning("Discovery could not validate any country — fallback: %s", reason)
        written, needs_key = await fallback.resolve(
            pool=pool,
            bedrock_client=bedrock_client,
            model_id=model_id,
            countries=codes,
            reason=reason,
        )
        total_written += written

    return DiscoveryReport(
        countries=all_codes,
        total_platforms=total_written,
        validated_countries=validated_countries,
        needs_key=needs_key,
        key_errors=list(dict.fromkeys(key_errors)),
        ran_at=datetime.now(timezone.utc),
    )
