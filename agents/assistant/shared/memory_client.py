import asyncio
import json
import logging
import ast
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from assistant.email.model import EmailMessage
from assistant.shared.base_llm_service import BaseLLMService

logger = logging.getLogger(__name__)


class MemoryClient(BaseLLMService):
    """Queries the MCP memory server for context relevant to a given topic.

    The memory server stores knowledge about the user gathered from past AI
    conversations (Claude, Codex, Antigravity). Before assessing or drafting a
    reply to an email, we search the memory server using the sender and subject
    as the query so the LLM has personal context about who is writing and why.

    Connects over the MCP streamable-HTTP transport, which uses a single HTTP
    endpoint (typically /mcp) for all JSON-RPC messages.
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

    def search(self, email: EmailMessage) -> str:
        """Search the MCP memory server for context relevant to an email.

        Asks the LLM to derive a list of search queries from the email, then
        runs each query against the memory server. Results are concatenated into
        a single plain-text block suitable for inclusion in an LLM prompt.

        Args:
            email: The incoming email whose sender, subject, and body preview are
                used to generate search queries.

        Returns:
            A multi-line string of memory results, or an empty string if the
            memory server is unreachable or the search fails.
        """
        prompt = f"""
              You are an email assistant. You read an email and return an array of keywords.
              These keywords will be used to search an mcp-memory server for all information that could enrich the context be helpful to better respond to this email 
              please analyse the given email and create the most effective search query that can yield the best results.

              Sender: {email.sender}
              Subject: {email.subject}
              Body:
              {email.body_preview}
              Rules:
                - Some APIs are very error prone to some symbol, try to keep your query simple and don't include symbols that may cause errors.
                - Memories are not always exact match of the words mentioned in the email. Examples:
                  If you find the word: Resume, the memory server might have a memory called job application, job, changing jobs etc.
                                        Certificate: Zeugnisse, Zertificate, Abschlusse, exam, etc.
                                        Dokumente: Documents, Unterlagen, Dateien, Files, folder, case etc.
                                        Bewerbung: Application, Jobbewerbung, Jobapplication, job application etc.
              Result:
                - The result MUST ONLY be a python array containing all recommended quries. No explination, no reasoning, no other string.
                - If the result contains anything other than pure array in python syntax, the program will fail.

          """
        try:
            raw = self._strip_markdown(self._invoke(prompt))
            queries = ast.literal_eval(raw)
            logger.debug(
                "Memory search: %d queries for email from %r",
                len(queries),
                email.sender,
            )
            result = "Context that might be relevant"
            for query in queries:
                result = result + "\n" + asyncio.run(self._search(query))
            return result
        except Exception:
            logger.warning(
                "Memory search failed for query %r", email.subject, exc_info=True
            )
            return ""


    _BANK_STATEMENT_QUERY = "Konto Auszug"

    # Keywords that indicate a memory is a bank statement (not infra logs etc.)
    _BANK_STATEMENT_KEYWORDS = [
        "kontoauszug", "konto", "iban", "bic", "buchung", "gutschrift",
        "lastschrift", "überweisung", "saldo", "girokonto", "sparkasse",
        "volksbank", "commerzbank", "deutsche bank", "dkb", "ing", "n26",
        "comdirect", "postbank", "bank", "habensaldo", "sollsaldo",
    ]

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

        e.g. 'https://adel-intelligence.com/mcp/mcp' → 'https://adel-intelligence.com'
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
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
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

    # Authoritative statement-month markers: the Sparkasse header
    # 'Kontoauszug 5/2026' in the PDF text, or the filename
    # 'Konto_..._Auszug_2026_0005.pdf' (statement number == month for
    # monthly statements). Substring date matching (_mentions_month) is only
    # a fallback — statement text routinely references neighbouring months
    # ('Rundfunk 04.2026 - 06.2026', Wertstellung dates, opening balance
    # dates), which previously pulled the SAME statement into several month
    # buckets and double-counted every transaction.
    _STATEMENT_HEADER_RE = re.compile(r"Kontoauszug\s+(\d{1,2})\s*/\s*(\d{4})")
    _TITLE_STATEMENT_RE  = re.compile(r"Auszug_(\d{4})_0*(\d{1,2})")

    def _statement_month(self, item: dict) -> str | None:
        """Derive the statement month 'YYYY-MM' from header text or filename."""
        m = self._STATEMENT_HEADER_RE.search(item.get("content") or "")
        if m:
            return f"{m.group(2)}-{int(m.group(1)):02d}"
        m = self._TITLE_STATEMENT_RE.search(item.get("title") or "")
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        return None

    def _mentions_month(self, text: str, month: str) -> bool:
        """Return True if *text* references *month* in any common German date format.

        Accepts '2026-01', '01.2026', '01/2026', and also the bare year+month in
        any order so that varied PDF layouts are all covered.
        """
        if not text or not month:
            return False
        try:
            year, mon = month.split("-")
        except ValueError:
            return month in text
        return (
            month in text               # 2026-01
            or f"{mon}.{year}" in text  # 01.2026
            or f"{mon}/{year}" in text  # 01/2026
        )

    def _looks_like_bank_statement(self, item: dict) -> bool:
        """Return True if the memory appears to be a bank statement.

        Checks title and content for German banking keywords to exclude
        technical logs, infrastructure notes, and other non-financial memories
        that happen to mention the target month.
        """
        haystack = (
            (item.get("title") or "") + " " + (item.get("content") or "")
        ).lower()
        return any(kw in haystack for kw in self._BANK_STATEMENT_KEYWORDS)

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
            # Primary: paginated REST API — deterministic and exhaustive.
            # Use "Auszug" so the ILIKE matches "Konto_NNNN-Auszug_..." filenames;
            # the full phrase "Konto Auszug" never appears verbatim in the title.
            # Month matching is done client-side by _mentions_month().
            all_items = await self._list_memories_api(
                query="Auszug", page_size=100
            )

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

    # Semantic queries for Adel's investing strategy (Trading 212 exports,
    # portfolio notes, watchlists) uploaded to memory.
    _INVESTING_STRATEGY_QUERIES = [
        "Trading 212 investing strategy portfolio holdings allocation pies",
        "Investment strategy stocks ETF portfolio watchlist risk profile",
    ]

    async def fetch_investing_strategy(self) -> str:
        """Search memory for Adel's uploaded investing strategy / portfolio notes."""
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

    # ── Agent analysis persistence ────────────────────────────────────────────
    #
    # Analyses (bank adviser, investing, day trading) are cached in MCP memory
    # so the dashboard can load the latest result without re-running the LLM,
    # and so each new run can build on the previous one.

    _ANALYSIS_TITLE_PREFIX = "agent-analysis"

    async def save_analysis(self, kind: str, payload: dict) -> None:
        """Persist an analysis result as a JSON memory.

        Args:
            kind: Analysis family, e.g. 'bank-adviser', 'investing', 'day-trading'.
            payload: JSON-serialisable result to store.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        title = f"{self._ANALYSIS_TITLE_PREFIX}:{kind} {timestamp}"
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(
                url=self._server_url, http_client=http_client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.call_tool(
                        "save",
                        {
                            "title": title,
                            "tags": [self._ANALYSIS_TITLE_PREFIX, kind],
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    )
        logger.info("Saved %s analysis to MCP memory as %r", kind, title)

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
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(
                url=self._server_url, http_client=http_client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.call_tool(
                        "save",
                        {
                            "title": f"Job Hunt Run — {date}",
                            "tags": ["job-search", "run-summary", "switzerland"],
                            "content": content,
                        },
                    )
        logger.debug("Job run summary saved to MCP memory for %s", date)

    async def _search(self, query: str) -> str:
        """Internal async implementation that performs the actual MCP call."""
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(
                url=self._server_url, http_client=http_client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("search", {"query": query})
                    if result.isError or not result.content:
                        return ""
                    return "\n".join(
                        item.text
                        for item in result.content
                        if hasattr(item, "text") and item.text
                    )
