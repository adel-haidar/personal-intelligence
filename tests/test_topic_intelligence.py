import json
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from fastapi import HTTPException
from private_internet.content.topic_intelligence import (
    MCPMemoryReader,
    TopicCandidate,
    TopicStorageService,
    ContentTopic,
)
from private_internet.content.research_service import WebResearchService, ResearchResult
from private_internet.content.jobs.topic_job import run_topic_intelligence_job


# ── Mocks Helper ───────────────────────────────────────────────

def _mock_conn(rowcount: int = 1, fetchone_val=None) -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = rowcount
    cursor.fetchone.return_value = fetchone_val
    conn.cursor.return_value = cursor
    return conn


# ── MCPMemoryReader Tests ──────────────────────────────────────

class TestMCPMemoryReader:
    @pytest.mark.anyio
    async def test_fetch_recent_memories(self):
        reader = MCPMemoryReader()
        mock_memories = [
            {"id": "m1", "title": "Weight loss", "content": "Lost 2kg", "tags": ["fitness"]},
            {"id": "m2", "title": "AWS prep", "content": "Studying for SAA-C03", "tags": ["aws"]},
        ]
        
        with patch("private_internet.content.topic_intelligence.list_memories", return_value=(mock_memories, 2)):
            result = await reader.fetch_recent_memories(limit=2, user_id="u1")
            
        assert len(result) == 2
        assert result[0]["id"] == "m1"
        assert result[1]["title"] == "AWS prep"

    @pytest.mark.anyio
    async def test_extract_topic_candidates_success(self):
        reader = MCPMemoryReader()
        memories = [{"id": "m1", "title": "Weight loss", "content": "Lost 2kg", "tags": ["fitness"]}]
        
        mock_llm_json = json.dumps([
            {
                "name": "Weight loss tracking with Apple Watch",
                "slug": "weight-loss-tracking-apple-watch",
                "keywords": ["weight", "apple watch", "fitness"],
                "source_ref": "m1"
            }
        ])
        
        mock_response = {
            "output": {
                "message": {
                    "content": [{"text": mock_llm_json}]
                }
            }
        }
        
        mock_client = MagicMock()
        mock_client.converse.return_value = mock_response
        
        with (
            patch("boto3.client", return_value=mock_client),
            patch("private_internet.content.topic_intelligence.get_settings")
        ):
            candidates = await reader.extract_topic_candidates(memories)
            
        assert len(candidates) == 1
        assert candidates[0].name == "Weight loss tracking with Apple Watch"
        assert candidates[0].slug == "weight-loss-tracking-apple-watch"
        assert candidates[0].keywords == ["weight", "apple watch", "fitness"]
        assert candidates[0].source_ref == "m1"
        assert candidates[0].source == "mcp_memory"


# ── WebResearchService Tests ────────────────────────────────────

class TestWebResearchService:
    @pytest.mark.anyio
    async def test_research_topic_structured_success(self):
        service = WebResearchService()
        topic = TopicCandidate("AWS prep", "aws-prep", ["aws"], "mcp_memory", "m1")
        
        mock_gemini_json = json.dumps([
            {
                "url": "https://aws.amazon.com/certification/certified-solutions-architect-associate/",
                "title": "AWS Certified Solutions Architect - Associate",
                "summary": "Official page detailing SAA-C03 certification."
            }
        ])
        
        mock_response = MagicMock()
        mock_response.text = mock_gemini_json
        mock_response.candidates = []
        
        service.model = MagicMock()
        service.model.generate_content.return_value = mock_response
        
        results = await service.research_topic(topic)
        assert len(results) == 1
        assert results[0].title == "AWS Certified Solutions Architect - Associate"
        assert results[0].url.startswith("https://aws")

    @pytest.mark.anyio
    async def test_research_topic_fallback_grounding(self):
        service = WebResearchService()
        topic = TopicCandidate("AWS prep", "aws-prep", ["aws"], "mcp_memory", "m1")
        
        # Invalid JSON returned by text model
        mock_response = MagicMock()
        mock_response.text = "Here is some general text not in JSON format."
        
        # Define mock structure for grounding metadata
        mock_web = MagicMock()
        mock_web.uri = "https://aws.amazon.com/fallback"
        mock_web.title = "Fallback AWS site"
        
        mock_chunk = MagicMock()
        mock_chunk.web = mock_web
        
        mock_metadata = MagicMock()
        mock_metadata.grounding_chunks = [mock_chunk]
        
        mock_candidate = MagicMock()
        mock_candidate.grounding_metadata = mock_metadata
        
        mock_response.candidates = [mock_candidate]
        
        service.model = MagicMock()
        service.model.generate_content.return_value = mock_response
        
        results = await service.research_topic(topic)
        assert len(results) == 1
        assert results[0].url == "https://aws.amazon.com/fallback"
        assert results[0].title == "Fallback AWS site"
        assert "grounding" in results[0].summary.lower()

    @pytest.mark.anyio
    async def test_assess_topic_relevance(self):
        service = WebResearchService()
        topic = TopicCandidate("AWS prep", "aws-prep", ["aws"], "mcp_memory", "m1")
        research = [ResearchResult("https://aws.amazon.com", "AWS", "AWS Study Guide")]
        
        mock_response = {
            "output": {
                "message": {
                    "content": [{"text": "Relevance score is: 0.85"}]
                }
            }
        }
        mock_client = MagicMock()
        mock_client.converse.return_value = mock_response
        
        with (
            patch("boto3.client", return_value=mock_client),
            patch("private_internet.content.research_service.get_settings")
        ):
            weight = await service.assess_topic_relevance(topic, research)
            
        assert weight == 0.85


# ── TopicStorageService Tests ───────────────────────────────────

class TestTopicStorageService:
    def test_is_duplicate_returns_true(self):
        storage = TopicStorageService()
        mock_db = _mock_conn(fetchone_val=(1,))
        
        result = storage.is_duplicate(mock_db, "test-slug", user_id="u1")
        assert result is True
        mock_db.cursor().execute.assert_called_once()

    def test_is_duplicate_returns_false(self):
        storage = TopicStorageService()
        mock_db = _mock_conn(fetchone_val=None)
        
        result = storage.is_duplicate(mock_db, "test-slug", user_id="u1")
        assert result is False

    def test_save_topic_new(self):
        storage = TopicStorageService()
        mock_db = _mock_conn(fetchone_val=None) # No existing topic found
        
        candidate = TopicCandidate("AWS prep", "aws-prep", ["aws"], "mcp_memory", "m1")
        research = [ResearchResult("https://aws.amazon.com", "AWS", "AWS Study Guide")]
        
        result = storage.save_topic(mock_db, candidate, research, 0.75, user_id="u1")
        
        assert isinstance(result, ContentTopic)
        assert result.name == "AWS prep"
        assert result.slug == "aws-prep"
        assert result.weight == 0.75
        mock_db.commit.assert_called_once()

    def test_save_topic_duplicate(self):
        storage = TopicStorageService()
        
        existing_row = {
            "id": "existing-id",
            "name": "AWS prep",
            "slug": "aws-prep",
            "source": "mcp_memory",
            "source_ref": "m1",
            "weight": 0.5,
            "used_count": 0,
            "last_used_at": None,
            "created_at": datetime.now(timezone.utc)
        }
        updated_row = {**existing_row, "weight": 0.9}
        
        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 1
        cursor.fetchone.side_effect = [existing_row, None, updated_row]
        mock_db.cursor.return_value = cursor
        
        candidate = TopicCandidate("AWS prep", "aws-prep", ["aws"], "mcp_memory", "m1")
        research = [ResearchResult("https://aws.amazon.com", "AWS", "AWS Study Guide")]
        
        result = storage.save_topic(mock_db, candidate, research, 0.9, user_id="u1")
        
        assert isinstance(result, ContentTopic)
        assert result.id == "existing-id"
        assert result.weight == 0.9  # updated weight
        mock_db.commit.assert_called_once()


# ── Job Orchestration Tests ────────────────────────────────────

class TestJobOrchestration:
    @pytest.mark.anyio
    async def test_run_topic_intelligence_job_success(self):
        mock_memories = [{"id": "m1", "title": "AWS Prep", "content": "Study details"}]
        mock_candidates = [TopicCandidate("AWS Prep", "aws-prep", ["aws"], "mcp_memory", "m1")]
        mock_research = [ResearchResult("https://aws.amazon.com", "AWS", "AWS Info")]
        
        mock_reader = MagicMock()
        mock_reader.fetch_recent_memories = AsyncMock(return_value=mock_memories)
        mock_reader.extract_topic_candidates = AsyncMock(return_value=mock_candidates)
        
        mock_research_service = MagicMock()
        mock_research_service.research_topic = AsyncMock(return_value=mock_research)
        mock_research_service.assess_topic_relevance = AsyncMock(return_value=0.8)
        
        mock_storage = MagicMock()
        mock_storage.is_duplicate.return_value = False
        mock_storage.save_topic.return_value = MagicMock()
        
        with (
            patch("private_internet.content.jobs.topic_job.MCPMemoryReader", return_value=mock_reader),
            patch("private_internet.content.jobs.topic_job.WebResearchService", return_value=mock_research_service),
            patch("private_internet.content.jobs.topic_job.TopicStorageService", return_value=mock_storage),
            patch("private_internet.content.jobs.topic_job._connect", return_value=MagicMock())
        ):
            await run_topic_intelligence_job(user_id="u1")
            
        mock_reader.fetch_recent_memories.assert_called_once()
        mock_reader.extract_topic_candidates.assert_called_once()
        mock_research_service.research_topic.assert_called_once()
        mock_research_service.assess_topic_relevance.assert_called_once()
        mock_storage.save_topic.assert_called_once()


# ── FastAPI Router Admin Endpoint Tests ───────────────────────

class TestRouterEndpoint:
    @pytest.mark.anyio
    async def test_run_job_endpoint_unauthorized(self):
        from private_internet.content.router import _require_internal_secret

        with (
            patch("os.getenv", return_value="super-secret"),
            pytest.raises(HTTPException) as exc_info
        ):
            await _require_internal_secret(x_internal_secret="wrong-secret")
        assert exc_info.value.status_code == 401

    @pytest.mark.anyio
    async def test_run_job_endpoint_authorized(self):
        from private_internet.content.router import (
            _require_internal_secret,
            run_topic_intelligence_job_endpoint,
        )

        mock_bg = MagicMock()
        with patch("os.getenv", return_value="super-secret"):
            # Dependency passes with the right secret…
            await _require_internal_secret(x_internal_secret="super-secret")
            # …and the endpoint enqueues the job
            response = await run_topic_intelligence_job_endpoint(background_tasks=mock_bg)

        assert response["status"] == "enqueued"
        mock_bg.add_task.assert_called_once()
