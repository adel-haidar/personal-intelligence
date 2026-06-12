# PHASE 2 — Topic Intelligence Engine
## Agent: Gemini (with web search grounding)
## Depends on: Phase 1 (DB + models must exist)

---

## Goal
Build the service that continuously monitors the MCP memory brain, detects interesting topics, enriches them with live web research, and writes them into `content_topics` + `content_research` tables. This is the "editorial brain" of the platform.

---

## Context
- MCP memory server: `https://adel-intelligence.com/mcp/mcp`
- MCP tools available: `save`, `search`, `fetch`
- Backend: FastAPI, Python
- DB models from Phase 1 are available
- This service runs as a **scheduled job** (every 6 hours via EventBridge → SQS → FastAPI worker)
- Use **Gemini's native web search grounding** for research (not a separate search API)
- AWS Bedrock is preferred but Gemini is explicitly assigned this phase for its research quality

---

## Task 1 — MCP Memory Reader

Create: `backend/app/content/topic_intelligence.py`

### Class: `MCPMemoryReader`

```python
class MCPMemoryReader:
    async def fetch_recent_memories(self, limit: int = 20) -> list[dict]:
        """
        Call MCP search tool with broad query to get recent memories.
        Parse returned JSON. Return list of memory dicts:
        { "id": str, "title": str, "content": str, "tags": list[str], "created_at": str }
        """

    async def extract_topic_candidates(self, memories: list[dict]) -> list[TopicCandidate]:
        """
        Call Bedrock Claude Haiku with this prompt structure:
        
        System: You are a topic extraction engine. Extract 3-5 distinct, 
        interesting topics from these memory snippets. For each topic output JSON:
        { "name": str, "slug": str, "keywords": list[str], "source_ref": str }
        
        Focus on: recent conversations, recurring themes, unresolved questions,
        personal milestones (certifications, weight, job applications), 
        geopolitical/cultural tensions the user finds interesting.
        
        Output ONLY a JSON array. No preamble.
        temperature=0
        """
```

### Class: `TopicCandidate` (dataclass)
```python
@dataclass
class TopicCandidate:
    name: str
    slug: str
    keywords: list[str]
    source: str          # 'mcp_memory'
    source_ref: str      # memory id
```

---

## Task 2 — Web Research Service

Create: `backend/app/content/research_service.py`

### Class: `WebResearchService`

This service calls the **Gemini 2.0 Flash** API (via `google-generativeai` SDK) with grounding enabled. Gemini's built-in Google Search grounding is used here instead of a separate search API to save cost and reduce complexity.

```python
import google.generativeai as genai

class WebResearchService:
    def __init__(self):
        # API key from env: GEMINI_API_KEY
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel(
            "gemini-2.0-flash",
            tools="google_search_retrieval"  # enables grounding
        )

    async def research_topic(self, topic: TopicCandidate) -> list[ResearchResult]:
        """
        Prompt structure:
        
        "Research the topic: '{topic.name}'
        
        Find:
        1. 3–5 authoritative articles or sources published in the last 6 months
        2. For each: title, URL, and a 2-sentence neutral summary
        3. Key statistics or data points if available
        4. Any controversy or opposing viewpoints
        
        Output ONLY a JSON array of objects:
        [{ "url": str, "title": str, "summary": str }]"
        
        Parse grounding_metadata from the response to extract cited URLs.
        Fall back to parsing the text if grounding_metadata is empty.
        Return list[ResearchResult].
        """

    async def assess_topic_relevance(self, topic: TopicCandidate, research: list[ResearchResult]) -> float:
        """
        Returns a relevance weight (0.0–1.0) using Haiku:
        - Is the topic currently trending?
        - Does it connect to the user's known interests?
        - Is there enough material for a video?
        temperature=0
        """
```

### Dataclass: `ResearchResult`
```python
@dataclass
class ResearchResult:
    url: str
    title: str
    summary: str
```

---

## Task 3 — Topic Deduplication + Storage

Still in `topic_intelligence.py`:

### Class: `TopicStorageService`

```python
class TopicStorageService:
    def is_duplicate(self, db: Session, slug: str, threshold_days: int = 14) -> bool:
        """
        Return True if a topic with this slug was already created in the last threshold_days.
        Prevents re-generating the same topic repeatedly.
        """

    def save_topic(self, db: Session, candidate: TopicCandidate, research: list[ResearchResult], weight: float) -> ContentTopic:
        """
        Insert into content_topics and content_research.
        If duplicate: update weight and append new research links only.
        """
```

---

## Task 4 — Orchestration Entry Point

Create: `backend/app/content/jobs/topic_job.py`

```python
async def run_topic_intelligence_job():
    """
    Full pipeline:
    1. MCPMemoryReader.fetch_recent_memories()
    2. MCPMemoryReader.extract_topic_candidates()
    3. For each candidate (parallel with asyncio.gather):
       a. WebResearchService.research_topic()
       b. WebResearchService.assess_topic_relevance()
       c. TopicStorageService.save_topic() if not duplicate
    4. Log summary: N topics added, N skipped (duplicate), N failed
    """
```

This function is called by the FastAPI background task scheduler in Phase 8.

---

## Task 5 — Admin Endpoint

Add to router:

```python
POST /api/content/jobs/topics/run
```

Triggers `run_topic_intelligence_job()` as a background task. Requires internal auth (check `X-Internal-Secret` header matches env var `INTERNAL_SECRET`). Used for manual triggering and EventBridge webhook.

---

## Environment Variables Required

Add to `.env` / AWS Parameter Store:
```
GEMINI_API_KEY=...
INTERNAL_SECRET=...   (if not already present)
```

---

## Topic Examples (for testing)

Run the job and verify it correctly detects topics like:
- "Relocating to Switzerland as a German software engineer"
- "AWS SAA-C03 exam preparation strategies"
- "Circular economy startup in Germany"
- "Weight loss tracking with Apple Watch"
- "USSR collapse parallels with modern Europe"

---

## Completion Criteria
- [ ] `run_topic_intelligence_job()` runs without error
- [ ] At least 3 topics inserted into `content_topics` after one run
- [ ] Each topic has at least 2 `content_research` rows
- [ ] Duplicate detection works (re-running within 14 days doesn't create duplicates)
- [ ] `GET /api/content/topics` returns populated results
- [ ] Weights between 0.3 and 0.9 (not all the same value)
