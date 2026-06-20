import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx

from assistant.shared.base_llm_service import BaseLLMService

logger = logging.getLogger(__name__)


class MemoryClient(BaseLLMService):
    """Queries the MCP memory server for context relevant to a given topic.

    The memory server stores knowledge about the user gathered from past AI
    conversations (Claude, Codex, Antigravity). Other agents (banking, job,
    trading) query it for the personal context the LLM needs — bank statements,
    job profile, prior analyses, and financial notes.

    Talks to Service A's per-user memory REST API (/api/memory*), forwarding the
    caller's bearer token so reads/writes are scoped to the right tenant. The
    server_url is the MCP endpoint (…/mcp/mcp); its scheme+host is reused as the
    REST base via `_api_base_url`.
    """

    def __init__(
        self, bedrock_client, model_id: str, server_url: str, token: str = None
    ):
        """Configure the client with the streamable-HTTP endpoint of the memory server.

        Args:
            server_url: The full URL of the MCP memory server endpoint,
                e.g. 'http://ec2-ip:8000/mcp'.
        """
        super().__init__(bedrock_client=bedrock_client, model_id=model_id)
        self._server_url = server_url
        self._token = token
        if "/mcp" not in server_url:
            logger.warning(
                "MCP_MEMORY_URL %r does not contain '/mcp' — "
                "memory searches will likely fail. "
                "Set MCP_MEMORY_URL to the streamable-HTTP endpoint, e.g. 'http://host:8000/mcp/mcp'.",
                server_url,
            )

    _BANK_STATEMENT_QUERY = "Konto Auszug bank statement"

    # Keywords that indicate a memory is a bank statement (not infra logs etc.).
    #
    # Split into two lists for clarity:
    #   _BANK_STATEMENT_KEYWORDS_LATIN  — ASCII/Latin terms (lowercased match)
    #   _BANK_STATEMENT_KEYWORDS_JP     — Japanese Unicode terms (exact substring)
    #
    # The combined check in _looks_like_bank_statement uses both.
    #
    # GERMAN / GENERIC LATIN TERMS
    _BANK_STATEMENT_KEYWORDS_LATIN = [
        # German Sparkasse / generic
        "kontoauszug", "konto", "iban", "bic", "buchung", "gutschrift",
        "lastschrift", "überweisung", "saldo", "girokonto", "sparkasse",
        "volksbank", "commerzbank", "deutsche bank", "dkb", "ing", "n26",
        "comdirect", "postbank", "habensaldo", "sollsaldo",
        # International English / generic
        "bank statement", "account statement", "bank account",
        "account balance", "transaction history", "statement of account",
        "balance", "debit", "credit", "swift", "sort code",
        # Currency markers that only appear in financial documents
        "jpy", "¥", "usd", "$", "gbp", "£", "chf",
        # Generic "bank" as a standalone word is kept but anchored below
        "bank",
    ]

    # JAPANESE TERMS (Unicode — checked against the original codepoint, not lowercased)
    _BANK_STATEMENT_KEYWORDS_JP = [
        "取引明細",   # transaction details / statement
        "口座",       # account
        "残高",       # balance
        "振込",       # bank transfer (credit)
        "入金",       # deposit / incoming payment
        "出金",       # withdrawal / outgoing payment
        "引き落とし", # direct debit
        "明細書",     # statement / itemised list
        "預金",       # deposit / savings account
        "通帳",       # passbook
        "銀行",       # bank
        "給与",       # salary
        "円",         # yen (kanji)
    ]

    # Kept for backward compatibility — callers that reference the old name
    # directly (e.g. external scripts) still work.
    _BANK_STATEMENT_KEYWORDS = _BANK_STATEMENT_KEYWORDS_LATIN

    # Semantic queries for supplementary financial context (prior analyses,
    # spending notes, savings goals). The bank statement itself is fetched
    # separately via fetch_bank_statement().
    _FINANCIAL_CONTEXT_QUERIES = [
        "Conversations or notes about personal finances, monthly spending, costs, budget, or savings goals",
        "Previous financial analysis, spending assessment, budget recommendations, or yearly savings progress",
    ]

    def fetch_bank_statement(self) -> str:
        """Fetch the most recent bank statement from the MCP memory server.

        Returns:
            The raw statement text, or an empty string if nothing is found.
        """
        try:
            return asyncio.run(self._search(self._BANK_STATEMENT_QUERY))
        except Exception:
            logger.warning("Failed to fetch bank statement from memory", exc_info=True)
            return ""

    def search_financial_context(self) -> str:
        """Search for supplementary financial context: prior analyses, spending
        conversations, and savings goal notes.

        Returns:
            A multi-line string of memory results, or an empty string if the
            memory server is unreachable or all queries return nothing.
        """
        parts: list[str] = []
        for query in self._FINANCIAL_CONTEXT_QUERIES:
            try:
                result = asyncio.run(self._search(query))
                if result:
                    parts.append(result)
            except Exception:
                logger.warning("Financial memory search failed for query %r", query, exc_info=True)

        return "\n".join(parts)

    @property
    def _api_base_url(self) -> str:
        """Derive the REST API base URL from the MCP server URL.

        e.g. 'https://your-domain.com/mcp/mcp' → 'https://your-domain.com'
        """
        parsed = urlparse(self._server_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def _list_memories_api(self, query: str = "", page_size: int = 100) -> list[dict]:
        """Fetch ALL memories via the REST API with full pagination.

        Unlike the MCP `search` tool (which returns a fixed top-k by vector
        similarity), this calls GET /api/memory with a text filter and pages
        through every result, guaranteeing an exhaustive and deterministic
        result set for a given query.

        Args:
            query: Optional text filter (matched against title and tags server-side).
            page_size: Items per page (max supported by the server).

        Returns:
            Complete list of matching memory dicts.
        """
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        all_items: list[dict] = []
        page = 1
        async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:
            while True:
                params: dict[str, str] = {"page": str(page), "page_size": str(page_size)}
                if query:
                    params["q"] = query
                resp = await client.get(f"{self._api_base_url}/api/memory", params=params)
                resp.raise_for_status()
                data = resp.json()
                all_items.extend(data.get("items", []))
                if page >= data.get("pages", 1):
                    break
                page += 1
        return all_items

    # Authoritative statement-month markers — checked in priority order:
    #
    # 1. German Sparkasse header: 'Kontoauszug 5/2026' in the PDF text.
    # 2. German filename:  'Konto_..._Auszug_2026_0005.pdf' (statement number
    #    == month for monthly Sparkasse statements).
    # 3. Japanese header:  '取引明細書' or '口座' with an ISO-style date block
    #    'YYYY/MM/DD'. The earliest YYYY/MM date in the document body is used
    #    as the statement month (most Japanese bank PDFs list transactions
    #    in date order, so the first date is always within the covered period).
    # 4. Generic ISO date: 'YYYY-MM-DD' anywhere in the content/title.
    #
    # Substring date matching (_mentions_month) is only a fallback — statement
    # text routinely references neighbouring months ('Rundfunk 04.2026 - 06.2026',
    # Wertstellung dates, opening-balance dates), which previously pulled the
    # SAME statement into several month buckets and double-counted transactions.
    _STATEMENT_HEADER_RE    = re.compile(r"Kontoauszug\s+(\d{1,2})\s*/\s*(\d{4})")
    _TITLE_STATEMENT_RE     = re.compile(r"Auszug_(\d{4})_0*(\d{1,2})")
    # Japanese/ISO date in body: YYYY/MM/DD or YYYY-MM-DD (used as fallback)
    _ISO_DATE_RE            = re.compile(r"(\d{4})[/-](\d{2})[/-]\d{2}")

    def _statement_month(self, item: dict) -> str | None:
        """Derive the statement month 'YYYY-MM' from header text or filename.

        Supports:
          - German Sparkasse header 'Kontoauszug N/YYYY'
          - German filename 'Auszug_YYYY_NNNN'
          - Japanese / international statements: earliest YYYY/MM or YYYY-MM-DD
            date found in the document body (handles formats like '2026/05/25').
        """
        content = item.get("content") or ""
        title   = item.get("title") or ""

        # 1. German header (highest confidence — explicitly states the period)
        m = self._STATEMENT_HEADER_RE.search(content)
        if m:
            return f"{m.group(2)}-{int(m.group(1)):02d}"

        # 2. German filename (e.g. Auszug_2026_0005.pdf)
        m = self._TITLE_STATEMENT_RE.search(title)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"

        # 3. First ISO-style date in the content (YYYY/MM/DD or YYYY-MM-DD).
        #    Used for Japanese statements (2026/05/25) and any locale that
        #    emits dates year-first.  We take the FIRST occurrence so that the
        #    opening/period header date is used rather than a trailing footnote.
        m = self._ISO_DATE_RE.search(content)
        if m:
            year, mon = m.group(1), m.group(2)
            # Sanity-guard: only trust years 2000–2099 and months 01–12.
            if 2000 <= int(year) <= 2099 and 1 <= int(mon) <= 12:
                return f"{year}-{mon}"

        return None

    def _mentions_month(self, text: str, month: str) -> bool:
        """Return True if *text* references *month* in any common date format.

        Accepts:
          '2026-01'   — ISO (also used in section headers)
          '01.2026'   — German dot format
          '01/2026'   — German slash format
          '2026/01'   — Japanese/ISO year-first slash format
          '2026/01/DD' — full Japanese date (first two components matched)
        """
        if not text or not month:
            return False
        try:
            year, mon = month.split("-")
        except ValueError:
            return month in text
        return (
            month in text                # 2026-01
            or f"{mon}.{year}" in text   # 01.2026  (German)
            or f"{mon}/{year}" in text   # 01/2026  (German)
            or f"{year}/{mon}" in text   # 2026/01  (Japanese/ISO year-first)
        )

    def _looks_like_bank_statement(self, item: dict) -> bool:
        """Return True if the memory appears to be a bank statement.

        Checks title and content for banking keywords to exclude technical
        logs, infrastructure notes, and other non-financial memories that
        happen to mention the target month.

        Supports:
          - German Sparkasse statements (original use-case)
          - English / international statements
          - Japanese statements (取引明細書, 口座, 残高, 振込, …)
        """
        raw = (item.get("title") or "") + " " + (item.get("content") or "")
        haystack_lower = raw.lower()
        # Latin/ASCII terms: check lowercased haystack
        if any(kw in haystack_lower for kw in self._BANK_STATEMENT_KEYWORDS_LATIN):
            return True
        # Japanese terms: check original codepoints (lowercasing is a no-op for
        # CJK but keeping it consistent with the rest of the method)
        if any(kw in raw for kw in self._BANK_STATEMENT_KEYWORDS_JP):
            return True
        return False

    # Re-uploads of the same PDF get a numeric suffix before the extension
    # ('Auszug_2025_0001_1.pdf'); strip it so they dedup against the original.
    # Suffix is 1-2 digits ('_1') — the 4-digit statement number must not match.
    _DUP_SUFFIX_RE = re.compile(r"(_\d{4})_\d{1,2}(\.pdf)", re.IGNORECASE)

    def _deduplicate_by_title(self, items: list[dict]) -> list[dict]:
        """Keep only the most recently created memory per normalized title.

        When a bank statement PDF is uploaded more than once the resulting
        memory chunks have identical titles (e.g. 'statement.pdf (2/3)') or
        a '_1' re-upload suffix. Sorting by created_at ascending and
        overwriting on the same key means the newest upload wins per chunk.
        """
        sorted_items = sorted(items, key=lambda m: m.get("created_at", ""))
        seen: dict[str, dict] = {}
        for item in sorted_items:
            title = item.get("title") or item["id"]
            key = self._DUP_SUFFIX_RE.sub(r"\1\2", title)
            seen[key] = item
        return list(seen.values())

    async def fetch_bank_statement_for_month(self, month: str) -> str:
        """Exhaustively fetch all bank-statement memories for *month* via REST API.

        Replaces the previous top-k semantic search (non-deterministic) with a
        paginated REST query that returns ALL matching memories, filtered
        client-side to those that actually mention the target month, and
        deduplicated by title to handle duplicate uploads.

        Falls back to the semantic search if the REST fetch fails or returns
        nothing, so the endpoint stays operational even if the API is down.

        Args:
            month: ISO year-month string, e.g. '2026-01'.
        """
        try:
            # Primary: fetch ALL memories and select bank statements by their
            # CONTENT (_looks_like_bank_statement checks German banking keywords in
            # title+content), NOT by filename. Retrieval must not depend on how a
            # statement happens to be named or tagged. Month matching is done
            # client-side from the statement header/content.
            all_items = await self._list_memories_api(page_size=100)

            statements = [
                item for item in all_items
                if self._looks_like_bank_statement(item)
                # Skip upload-event stubs ('File uploaded at ... Path: ...')
                and not (item.get("title") or "").startswith("Uploaded file:")
            ]

            # Primary: exact statement-month match from the 'Kontoauszug N/YYYY'
            # header or the filename. Prevents a statement that merely MENTIONS
            # a neighbouring month from being analysed twice.
            relevant = [
                item for item in statements
                if self._statement_month(item) == month
            ]

            if not relevant:
                # Fallback for statements without a parsable header/filename:
                # substring date match (legacy behaviour).
                relevant = [
                    item for item in statements
                    if self._statement_month(item) is None
                    and (
                        self._mentions_month(item.get("content", ""), month)
                        or self._mentions_month(item.get("title", ""), month)
                    )
                ]

            if not relevant:
                logger.info(
                    "No bank-statement memories found for %s via REST API "
                    "(checked %d items total)",
                    month, len(all_items),
                )
                return ""

            deduplicated = self._deduplicate_by_title(relevant)
            # Sort by title so multi-chunk PDFs appear in order (Part 1, 2, …)
            deduplicated.sort(key=lambda m: m.get("title", ""))

            logger.info(
                "Exhaustive fetch for %s: %d raw items → %d after filter+dedup",
                month, len(all_items), len(deduplicated),
            )
            return "\n\n".join(item["content"] for item in deduplicated)

        except Exception:
            logger.warning(
                "Exhaustive REST fetch failed for month %r — falling back to semantic search",
                month,
                exc_info=True,
            )
            return await self._search(f"bank statement {month}")

    async def fetch_financial_context(self) -> str:
        """Async version: search for supplementary financial context."""
        parts: list[str] = []
        for query in self._FINANCIAL_CONTEXT_QUERIES:
            try:
                result = await self._search(query)
                if result:
                    parts.append(result)
            except Exception:
                logger.warning("Financial memory search failed for query %r", query, exc_info=True)
        return "\n".join(parts)

    # Semantic queries for the user's investing strategy (broker exports,
    # portfolio notes, watchlists) uploaded to memory.
    _INVESTING_STRATEGY_QUERIES = [
        "investing strategy portfolio holdings allocation pies broker export",
        "Investment strategy stocks ETF portfolio watchlist risk profile",
    ]

    async def fetch_investing_strategy(self) -> str:
        """Search memory for the user's uploaded investing strategy / portfolio notes."""
        parts: list[str] = []
        for query in self._INVESTING_STRATEGY_QUERIES:
            try:
                result = await self._search(query)
                if result:
                    parts.append(result)
            except Exception:
                logger.warning(
                    "Investing strategy search failed for query %r", query, exc_info=True
                )
        return "\n".join(parts)

    _JOB_PROFILE_QUERIES = [
        "resume CV curriculum vitae",
        "work experience skills technologies",
        "job preferences target role desired position salary location",
    ]

    async def fetch_job_profile(self) -> str:
        """Search the CALLER's brain for their résumé / skills / job preferences.

        Returns the concatenated profile text, or '' if the user has no job-relevant
        memories. The job-hunt agent uses this to score against the caller's own
        profile and to gate the scrape — a user with no profile is not scraped
        (so they never receive the owner's matches)."""
        seen: set[str] = set()
        parts: list[str] = []
        for query in self._JOB_PROFILE_QUERIES:
            try:
                result = await self._search(query)
                if result and result not in seen:
                    seen.add(result)
                    parts.append(result)
            except Exception:
                logger.warning("Job-profile search failed for query %r", query, exc_info=True)
        return "\n".join(parts).strip()

    # ── Agent analysis persistence ────────────────────────────────────────────
    #
    # Analyses (bank adviser, investing, day trading) are cached in MCP memory
    # so the dashboard can load the latest result without re-running the LLM,
    # and so each new run can build on the previous one.

    _ANALYSIS_TITLE_PREFIX = "agent-analysis"

    async def _save_text_api(self, title: str, content: str, tags: list[str]) -> None:
        """Persist a memory via Service A's per-user REST API (POST /api/memory/text).

        The bearer token is forwarded so Service A scopes the save to the caller's
        own brain (platform JWT → that user; INTERNAL_SECRET → seed admin).
        """
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:
            resp = await client.post(
                f"{self._api_base_url}/api/memory/text",
                json={"title": title, "content": content, "tags": tags},
            )
            resp.raise_for_status()

    async def save_analysis(self, kind: str, payload: dict) -> None:
        """Persist an analysis result as a JSON memory.

        Args:
            kind: Analysis family, e.g. 'bank-adviser', 'investing', 'day-trading'.
            payload: JSON-serialisable result to store.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = f"{self._ANALYSIS_TITLE_PREFIX}:{kind} {timestamp}"
        await self._save_text_api(
            title=title,
            content=json.dumps(payload, ensure_ascii=False),
            tags=[self._ANALYSIS_TITLE_PREFIX, kind],
        )
        logger.info("Saved %s analysis to memory as %r", kind, title)

    async def fetch_latest_analysis(self, kind: str) -> dict | None:
        """Fetch the most recent saved analysis of the given kind, or None."""
        prefix = f"{self._ANALYSIS_TITLE_PREFIX}:{kind}"
        try:
            items = await self._list_memories_api(query=prefix, page_size=100)
        except Exception:
            logger.warning("Failed to list %s analyses", kind, exc_info=True)
            return None

        candidates = [
            item for item in items
            if (item.get("title") or "").startswith(prefix)
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda m: m.get("created_at", ""))
        try:
            return json.loads(latest.get("content") or "")
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Latest %s analysis %r is not valid JSON — ignoring",
                kind, latest.get("title"),
            )
            return None

    # Marker written by the frontend first-run popup into the user's brain.
    # Format: ANNUAL_SAVINGS_GOAL=<positive number> <CURRENCY CODE>
    # Example: ANNUAL_SAVINGS_GOAL=12000 EUR
    _SAVINGS_GOAL_RE = re.compile(
        r"ANNUAL_SAVINGS_GOAL=(\d+(?:\.\d+)?)\s+([A-Z]{3})"
    )

    async def fetch_savings_goal(self) -> tuple[float, str] | None:
        """Read the user's annual savings goal from their brain.

        The frontend first-run popup saves the goal as a plain-text memory
        containing a machine-parseable marker line:
            ANNUAL_SAVINGS_GOAL=<number> <CURRENCY>
        e.g.  ANNUAL_SAVINGS_GOAL=12000 EUR

        Searches the brain with a semantic query, then scans all returned
        memory bodies for the marker regex.  Returns (amount, currency) if
        found, or None if the goal has not been set yet.

        This uses the same async HTTP + bearer-token pattern as _search so
        the result is always scoped to the caller's own brain.
        """
        try:
            text = await self._search("annual savings goal target")
            if text:
                m = self._SAVINGS_GOAL_RE.search(text)
                if m:
                    return float(m.group(1)), m.group(2)
        except Exception:
            logger.warning("fetch_savings_goal search failed", exc_info=True)
        return None

    # Marker written by the frontend first-run popup into the user's brain.
    # Format: TARGET_WEIGHT_KG=<positive number>
    # Example: TARGET_WEIGHT_KG=70
    _WEIGHT_GOAL_MARKER_RE = re.compile(r"TARGET_WEIGHT_KG\s*=\s*([0-9]+(?:\.[0-9]+)?)")

    async def fetch_weight_goal(self) -> float | None:
        """Read the user's target weight goal from their brain.

        The frontend first-run popup saves the goal as a plain-text memory
        containing a machine-parseable marker line::

            TARGET_WEIGHT_KG=<number>   e.g.  TARGET_WEIGHT_KG=70

        Searches the brain with a semantic query, then scans returned memory
        bodies for the marker regex. Returns the goal as a float (kg) if found,
        or None if the goal has not been set yet — the caller must handle None
        by omitting goal-relative output rather than inventing a default.

        Uses the same async HTTP + bearer-token pattern as _search so the
        result is always scoped to the caller's own brain.
        """
        try:
            text = await self._search("target weight goal kg")
            if text:
                m = self._WEIGHT_GOAL_MARKER_RE.search(text)
                if m:
                    return float(m.group(1))
        except Exception:
            logger.warning("fetch_weight_goal search failed", exc_info=True)
        return None

    async def save_job_run(
        self,
        date: str,
        strong_count: int,
        good_count: int,
        top_summary: str,
    ) -> None:
        """Persist a job hunt run summary to the MCP memory server."""
        content = (
            f"Run on {date}. {strong_count} strong matches, {good_count} good matches saved to DB."
            f"{top_summary}"
        )
        await self._save_text_api(
            title=f"Job Hunt Run — {date}",
            content=content,
            tags=["job-search", "run-summary", "switzerland"],
        )
        logger.debug("Job run summary saved to memory for %s", date)

    async def _search(self, query: str) -> str:
        """Semantic memory search via Service A's per-user REST API.

        Calls GET /api/memory/search?q=… with the forwarded bearer token so the
        results are scoped to the caller's own brain (platform JWT → that user;
        INTERNAL_SECRET / legacy OAuth → seed admin). Concatenates the returned
        memories' content into a single plain-text block for the LLM prompt.
        """
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(headers=headers, timeout=120.0) as client:
            resp = await client.get(
                f"{self._api_base_url}/api/memory/search",
                params={"q": query},
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        return "\n".join(
            item["content"] for item in items if item.get("content")
        )
