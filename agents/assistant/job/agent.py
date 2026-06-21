import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

from assistant.job.countries import name_for
from assistant.job.db import count_all, init_pool, upsert_match
from assistant.job.models import JobListing, MatchResult, RunReport, ScoredListing
from assistant.job.platforms import catalog as platform_catalog
from assistant.job.report import format_report
from assistant.job.scorer import JobScorer
from assistant.job.scrapers.base import ScraperError
from assistant.job.scrapers.rapidapi import RapidApiScraper

logger = logging.getLogger(__name__)

# Neutral fallback queries used ONLY when profile-derived queries cannot be
# generated (e.g. Bedrock unavailable). Intentionally generic — not tied to
# any specific profession, stack, or person.
_FALLBACK_QUERIES: list[tuple[str, Optional[str]]] = [
    ("professional job opening", None),
    ("experienced professional position", None),
]

_QUERY_GENERATION_PROMPT = """\
You are a job search assistant. Given a candidate's profile (CV / résumé / skills / \
job preferences), generate 3 to 5 concise job search queries that would surface \
relevant job listings on international job boards.

Rules:
- Each query should be a short phrase (2-5 words) representing the role or skill set.
- Do NOT include location in the queries — location is handled separately.
- Derive queries ONLY from what is stated in the profile. Do not invent skills or roles.
- Return ONLY a valid JSON array of strings, nothing else. Example:
  ["Middle School Teacher", "Educational Coordinator", "Curriculum Developer"]

=== CANDIDATE PROFILE ===
{profile}

Return the JSON array now:"""


def derive_queries_from_profile(
    bedrock_client,
    model_id: str,
    candidate_profile: str,
) -> list[tuple[str, Optional[str]]]:
    """Use the LLM to derive role-based search queries from the candidate's profile.

    Returns a list of (query_string, city_hint) tuples compatible with the
    scraper interface. City hints are always None — location is handled at
    the country-code level in run_agent.

    Falls back to _FALLBACK_QUERIES if the LLM call fails or returns an empty list.
    """
    if not candidate_profile or not candidate_profile.strip():
        return list(_FALLBACK_QUERIES)

    prompt = _QUERY_GENERATION_PROMPT.format(profile=candidate_profile[:4000])
    try:
        response = bedrock_client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 512, "temperature": 0},
        )
        raw = response["output"]["message"]["content"][0]["text"].strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()
        # Find the JSON array
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.warning("Query-generation LLM returned no JSON array: %r", raw[:200])
            return list(_FALLBACK_QUERIES)
        queries_raw = json.loads(raw[start:end + 1])
        if not isinstance(queries_raw, list) or not queries_raw:
            logger.warning("Query-generation returned empty or non-list: %r", queries_raw)
            return list(_FALLBACK_QUERIES)
        queries = [(str(q).strip(), None) for q in queries_raw if str(q).strip()]
        if not queries:
            return list(_FALLBACK_QUERIES)
        logger.info("Profile-derived queries (%d): %s", len(queries), [q for q, _ in queries])
        return queries
    except Exception:
        logger.warning("Failed to derive queries from profile — using fallback", exc_info=True)
        return list(_FALLBACK_QUERIES)


def _dedup_key(listing: JobListing) -> str:
    return (
        f"{listing.company.lower().strip()}"
        f"|{listing.title.lower().strip()}"
        f"|{listing.location.lower().strip()}"
    )


_SEARCH_PAGE_TITLE_PATTERNS = [
    re.compile(r"^\d+\s+job", re.I),
    re.compile(r"^\d[\d\s,]+job", re.I),
    re.compile(r"job offers?\s*-\s*", re.I),
    re.compile(r"job offer[s]? in\s+", re.I),
]


def is_search_results_page(listing: JobListing) -> bool:
    title_lower = listing.title.lower().strip()
    return any(p.search(title_lower) for p in _SEARCH_PAGE_TITLE_PATTERNS)


async def _build_platform_filter(
    database_url: str, country_codes: list[str], platform_keys: list[str]
) -> Optional[tuple[set[str], set[str]]]:
    """Resolve selected platform_keys to (publisher-name set, domain set) for
    matching JSearch results. Returns None when no usable filter applies (no
    selection, or the keys aren't in the catalog) — meaning "don't filter"."""
    if not platform_keys:
        return None
    try:
        pool = await platform_catalog.init_pool(database_url)
        by_country = await platform_catalog.list_for_countries(pool, country_codes)
    except Exception:
        logger.warning("Could not load platform catalog for filtering", exc_info=True)
        return None

    wanted = {k.lower() for k in platform_keys}
    names: set[str] = set()
    domains: set[str] = set()
    for plats in by_country.values():
        for p in plats:
            if p.platform_key.lower() in wanted:
                names.add(p.display_name.strip().lower())
                if p.domain:
                    domains.add(p.domain.strip().lower())
    if not names and not domains:
        return None
    return names, domains


def _listing_matches_platforms(
    listing: JobListing, names: set[str], domains: set[str]
) -> bool:
    """True if the listing's publisher/apply-publishers or URL match a selected
    platform by board name or domain (case-insensitive)."""
    pubs = [listing.publisher or "", *listing.apply_publishers]
    pubs_lower = [p.strip().lower() for p in pubs if p and p.strip()]
    if any(p in names for p in pubs_lower):
        return True
    haystack = " ".join(pubs_lower) + " " + (listing.job_url or "").lower()
    return any(d and d in haystack for d in domains)


async def run_agent(
    database_url: str,
    bedrock_client,
    model_id: str,
    rapidapi_key: Optional[str],
    rapidapi_host: str,
    memory_client,
    delay_seconds: float,
    max_per_query: int,
    user_id: str,
    countries: list[str],
    score_concurrency: int = 6,
    platforms: Optional[list[str]] = None,
) -> RunReport:
    timestamp = datetime.utcnow()
    pool = await init_pool(database_url)

    # `countries` are ISO alpha-2 codes chosen by the user in the dashboard.
    # Display names are used for scoring context and the report.
    country_codes = [c.upper() for c in countries if c]
    country_names = [name_for(c) for c in country_codes]

    # Per-user job profile from the CALLER's brain. Score against it; if the user
    # has no profile (no résumé/skills/preferences in their brain), skip the scrape
    # entirely so they never receive another user's matches.
    candidate_profile = ""
    if memory_client is not None:
        try:
            candidate_profile = await memory_client.fetch_job_profile()
        except Exception:
            logger.warning("Could not fetch caller's job profile from brain", exc_info=True)
    scorer = JobScorer(
        bedrock_client=bedrock_client, model_id=model_id,
        candidate_profile=candidate_profile,
        target_countries=country_names,
    )

    # JSearch (RAPIDAPI_KEY) is the sole, international job source. It routes
    # through its own proxy infrastructure, so it works from EC2 where LinkedIn
    # and Indeed block the host directly. Local-market scrapers (jobs.ch,
    # StepStone) were removed — the platform now serves any country.
    scrapers = []
    if rapidapi_key:
        scrapers.append(
            RapidApiScraper(rapidapi_key, rapidapi_host, delay_seconds, max_per_query)
        )
    else:
        logger.warning(
            "RAPIDAPI_KEY not set — JSearch is the only job source and is "
            "unavailable. Set RAPIDAPI_KEY to enable the scrape."
        )

    if not candidate_profile.strip():
        # No profile in the caller's brain → no scraping. Returns a zeroed report
        # rather than the owner's jobs. The user should add their résumé/job
        # preferences to their Brain, then re-run.
        logger.info("No job profile in brain for user %s — skipping scrape", user_id)
        scrapers = []

    # Derive search queries from the caller's own profile so Yuki gets teaching
    # queries, an engineer gets engineering queries, etc. Falls back to generic
    # neutral queries only if derivation fails.
    search_queries: list[tuple[str, Optional[str]]]
    if candidate_profile.strip() and scrapers:
        search_queries = derive_queries_from_profile(
            bedrock_client=bedrock_client,
            model_id=model_id,
            candidate_profile=candidate_profile,
        )
    else:
        search_queries = []

    all_raw: list[JobListing] = []
    platforms_used: set[str] = set()
    scrape_errors: list[str] = []

    for code in country_codes:
        for query, city in search_queries:
            for scraper in scrapers:
                try:
                    results = await scraper.search(query, code, city)
                    all_raw.extend(results)
                    if results:
                        platforms_used.add(scraper.name)
                except ScraperError as exc:
                    # A real source failure (quota/key/5xx) — remember the reason
                    # so an empty run can explain itself instead of saying "0".
                    scrape_errors.append(str(exc))
                    logger.warning(
                        "Scraper %s error for %r in %s: %s", scraper.name, query, code, exc
                    )
                except Exception:
                    logger.exception(
                        "Scraper %s failed for %r in %s", scraper.name, query, code
                    )

    raw_count = len(all_raw)

    seen_urls: set[str] = set()
    seen_keys: set[str] = set()
    deduped: list[JobListing] = []
    for listing in all_raw:
        if listing.job_url in seen_urls:
            continue
        key = _dedup_key(listing)
        if key in seen_keys:
            continue
        seen_urls.add(listing.job_url)
        seen_keys.add(key)
        deduped.append(listing)

    # Restrict to the platforms the user selected (by JSearch publisher/domain).
    # No selection → keep everything (current behaviour). Applied post-dedup,
    # pre-scoring so we never pay to score a board the user didn't ask for.
    platform_filter = await _build_platform_filter(
        database_url, country_codes, platforms or []
    )
    if platform_filter is not None:
        names, domains = platform_filter
        before = len(deduped)
        deduped = [
            l for l in deduped if _listing_matches_platforms(l, names, domains)
        ]
        logger.info(
            "Platform filter %s: kept %d of %d listings",
            sorted(platforms or []), len(deduped), before,
        )

    dedup_count = len(deduped)
    logger.info("Collected %d raw, %d after dedup", raw_count, dedup_count)

    strong_matches: list[ScoredListing] = []
    good_matches: list[ScoredListing] = []
    hard_rejected_count = 0
    hard_rejected_by_reason: dict[str, int] = defaultdict(int)
    rejection_log: dict[str, list[str]] = defaultdict(list)
    db_saved = 0

    # Search-results pages are rejected up front with a cheap regex — no LLM call.
    to_score: list[JobListing] = []
    for listing in deduped:
        if is_search_results_page(listing):
            logger.info(
                "SEARCH_RESULTS_PAGE rejected: %r | %s", listing.title, listing.job_url
            )
            hard_rejected_count += 1
            hard_rejected_by_reason["SEARCH_RESULTS_PAGE"] += 1
            rejection_log["SEARCH_RESULTS_PAGE"].append(
                f"{listing.company} — {listing.title}"
            )
            continue
        to_score.append(listing)

    # Score listings concurrently. The per-listing Bedrock call dominates the
    # run's wall time, so scoring them one-at-a-time made a run take 10-15 min;
    # a bounded semaphore keeps that to a couple of minutes without hammering
    # Bedrock into throttling. Scoring (read-only LLM) is parallel; the DB
    # upserts and aggregation below stay sequential and deterministic.
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(max(1, score_concurrency))

    async def _score(listing: JobListing) -> tuple[JobListing, Optional[MatchResult]]:
        async with sem:
            return listing, await loop.run_in_executor(None, scorer.score, listing)

    scored_pairs = await asyncio.gather(*(_score(item) for item in to_score))

    for listing, result in scored_pairs:
        if result is None:
            continue

        if result.disqualified:
            hard_rejected_count += 1
            code = result.disqualifier_code or "UNKNOWN"
            hard_rejected_by_reason[code] += 1
            rejection_log[code].append(f"{listing.company} — {listing.title}")
            continue

        tier = result.match_tier
        if tier in ("STRONG_MATCH", "GOOD_MATCH"):
            row_id, is_new = await upsert_match(pool, listing, result, user_id=user_id)
            scored = ScoredListing(listing=listing, result=result, db_id=row_id)
            if is_new:
                db_saved += 1
            if tier == "STRONG_MATCH":
                strong_matches.append(scored)
            else:
                good_matches.append(scored)
        elif tier == "WEAK_MATCH":
            logger.debug(
                "WEAK_MATCH score=%s: %s @ %s",
                result.score,
                listing.title,
                listing.company,
            )

    db_total = await count_all(pool)

    # When a run comes back empty, say WHY — an empty scrape is the single most
    # confusing outcome ("ran fast, found nothing") and it has several distinct,
    # actionable causes. Surfaced in the report so it never reads as a bare "0".
    notice: Optional[str] = None
    if raw_count == 0:
        if not candidate_profile.strip():
            notice = (
                "No job profile found in your Brain. The job hunt scores against "
                "your own résumé / skills / preferences and won't scrape without "
                "one — add them to your Brain, then run again."
            )
        elif not scrapers:
            notice = (
                "No job source is configured: RAPIDAPI_KEY is not set, so the "
                "JSearch source is unavailable."
            )
        elif scrape_errors:
            reasons = "; ".join(dict.fromkeys(scrape_errors))  # de-dup, keep order
            notice = (
                f"The job source returned no listings because it errored: {reasons}. "
                "This is usually an exhausted API quota or an invalid key."
            )
        else:
            notice = (
                "The job source returned no listings for your queries in "
                f"{', '.join(country_names) or 'the selected countries'}. "
                "Try more or different countries, or broaden the skills/roles in "
                "your Brain profile."
            )
        logger.warning("Empty run for user %s — %s", user_id, notice)

    if memory_client:
        try:
            top = strong_matches[0] if strong_matches else (good_matches[0] if good_matches else None)
            top_summary = ""
            if top:
                top_summary = (
                    f" Top match: {top.listing.title} at {top.listing.company},"
                    f" {top.listing.country} — score {top.result.score}/100."
                    f" {top.result.ai_summary or ''}"
                )
            await memory_client.save_job_run(
                date=timestamp.strftime("%Y-%m-%d"),
                strong_count=len(strong_matches),
                good_count=len(good_matches),
                top_summary=top_summary,
            )
        except Exception:
            logger.exception("Failed to save run summary to MCP memory")

    report = RunReport(
        timestamp=timestamp,
        platforms=sorted(platforms_used),
        countries=country_names,
        raw_count=raw_count,
        dedup_count=dedup_count,
        hard_rejected_count=hard_rejected_count,
        hard_rejected_by_reason=dict(hard_rejected_by_reason),
        scored_count=dedup_count - hard_rejected_count,
        strong_matches=strong_matches,
        good_matches=good_matches,
        rejection_log=dict(rejection_log),
        db_saved_this_run=db_saved,
        db_cumulative=db_total,
        notice=notice,
    )

    logger.info(
        "Run complete — strong: %d | good: %d | saved: %d",
        len(strong_matches),
        len(good_matches),
        db_saved,
    )
    print(format_report(report))
    return report
