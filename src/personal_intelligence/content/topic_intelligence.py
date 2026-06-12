import os
import json
import uuid
import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional
from psycopg2.extras import RealDictCursor

import boto3
from personal_intelligence.config import get_settings
from personal_intelligence.memory.service import list_memories

logger = logging.getLogger(__name__)


@dataclass
class TopicCandidate:
    name: str
    slug: str
    keywords: List[str]
    source: str          # 'mcp_memory'
    source_ref: str      # memory id or comma-separated ids


@dataclass
class ContentTopic:
    id: str
    name: str
    slug: str
    source: str
    source_ref: str
    weight: float = 0.5
    used_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MCPMemoryReader:
    async def fetch_recent_memories(self, limit: int = 20) -> List[dict]:
        """
        Call local memory service to retrieve the most recent memories.
        Returns list of memory dicts:
        { "id": str, "title": str, "content": str, "tags": list[str], "created_at": str }
        """
        loop = asyncio.get_event_loop()
        try:
            items, _ = await loop.run_in_executor(
                None, lambda: list_memories(page=1, page_size=limit)
            )
            return items
        except Exception as e:
            logger.error(f"Failed to fetch recent memories from local service: {e}", exc_info=True)
            return []

    async def extract_topic_candidates(self, memories: List[dict]) -> List[TopicCandidate]:
        """
        Call Bedrock Claude Haiku with the topic extraction prompt.
        Focuses on recent conversations, milestones, recurring themes, etc.
        """
        if not memories:
            logger.warning("No memories provided for topic extraction.")
            return []

        memories_text = ""
        for m in memories:
            memories_text += f"Memory ID: {m.get('id')}\n"
            memories_text += f"Title: {m.get('title')}\n"
            memories_text += f"Content: {m.get('content')}\n"
            memories_text += f"Tags: {', '.join(m.get('tags') or [])}\n"
            memories_text += f"Created At: {m.get('created_at')}\n"
            memories_text += "---\n"

        system_prompt = (
            "You are a topic extraction engine. Extract 3-5 distinct, "
            "interesting topics from these memory snippets. For each topic output JSON:\n"
            '{ "name": str, "slug": str, "keywords": list[str], "source_ref": str }\n\n'
            "Focus on: recent conversations, recurring themes, unresolved questions, "
            "personal milestones (certifications, weight, job applications), "
            "geopolitical/cultural tensions the user finds interesting.\n\n"
            "Output ONLY a JSON array. No preamble, no explanation, no markdown format fences."
        )

        user_prompt = f"Here are the memories:\n\n{memories_text}"

        settings = get_settings()
        # Default model for AWS Bedrock Haiku. Fallback to Nova or other configured model if needed.
        model_id = os.getenv("BEDROCK_HAIKU_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        
        loop = asyncio.get_event_loop()
        
        def invoke_bedrock():
            client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
            try:
                response = client.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    system=[{"text": system_prompt}],
                    inferenceConfig={"temperature": 0.0}
                )
                return response["output"]["message"]["content"][0]["text"]
            except Exception as e:
                logger.warning(f"Failed to invoke Bedrock with Claude 3 Haiku: {e}. Trying fallback model.")
                fallback_model = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
                response = client.converse(
                    modelId=fallback_model,
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    system=[{"text": system_prompt}],
                    inferenceConfig={"temperature": 0.0}
                )
                return response["output"]["message"]["content"][0]["text"]

        try:
            response_text = await loop.run_in_executor(None, invoke_bedrock)
        except Exception as e:
            logger.error(f"Bedrock invocation failed completely: {e}", exc_info=True)
            return []

        # Clean JSON markdown blocks if any
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            else:
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

        try:
            candidates_data = json.loads(clean_text)
            candidates = []
            for item in candidates_data:
                candidates.append(TopicCandidate(
                    name=item["name"],
                    slug=item["slug"],
                    keywords=item["keywords"],
                    source="mcp_memory",
                    source_ref=item["source_ref"]
                ))
            return candidates
        except Exception as e:
            logger.error(f"Failed to parse JSON response from Bedrock: {response_text}. Error: {e}", exc_info=True)
            return []


class TopicStorageService:
    def is_duplicate(self, db, slug: str, threshold_days: int = 14) -> bool:
        """
        Return True if a topic with this slug was already created in the last threshold_days.
        Prevents re-generating the same topic repeatedly.
        """
        cur = db.cursor()
        try:
            cur.execute(
                """SELECT 1 FROM content_topics 
                   WHERE slug = %s AND created_at >= %s - INTERVAL '%s days'""",
                (slug, datetime.now(timezone.utc), threshold_days)
            )
            exists = cur.fetchone() is not None
            return exists
        except Exception as e:
            logger.error(f"Failed to check duplicate for slug {slug}: {e}", exc_info=True)
            return False
        finally:
            cur.close()

    def save_topic(self, db, candidate: TopicCandidate, research: list, weight: float) -> ContentTopic:
        """
        Insert into content_topics and content_research.
        If duplicate: update weight and append new research links only.
        """
        cur = db.cursor(cursor_factory=RealDictCursor)
        try:
            # Check if topic already exists by slug
            cur.execute("SELECT * FROM content_topics WHERE slug = %s", (candidate.slug,))
            row = cur.fetchone()

            if row:
                topic_id = row["id"]
                # Update weight to the new relevance weight
                cur.execute(
                    "UPDATE content_topics SET weight = %s WHERE id = %s",
                    (weight, topic_id)
                )

                # Append new research links only
                for res in research:
                    cur.execute(
                        "SELECT 1 FROM content_research WHERE topic_id = %s AND url = %s",
                        (topic_id, res.url)
                    )
                    if cur.fetchone() is None:
                        research_id = str(uuid.uuid4())
                        cur.execute(
                            """INSERT INTO content_research (id, topic_id, url, title, summary)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (research_id, topic_id, res.url, res.title, res.summary)
                        )
                db.commit()
                
                # Fetch updated topic row
                cur.execute("SELECT * FROM content_topics WHERE id = %s", (topic_id,))
                updated_row = cur.fetchone()
                
                return ContentTopic(
                    id=updated_row["id"],
                    name=updated_row["name"],
                    slug=updated_row["slug"],
                    source=updated_row["source"],
                    source_ref=updated_row["source_ref"],
                    weight=updated_row["weight"],
                    used_count=updated_row["used_count"],
                    last_used_at=updated_row["last_used_at"],
                    created_at=updated_row["created_at"]
                )
            else:
                topic_id = str(uuid.uuid4())
                created_at = datetime.now(timezone.utc)
                
                cur.execute(
                    """INSERT INTO content_topics (id, name, slug, source, source_ref, weight, used_count, last_used_at, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (topic_id, candidate.name, candidate.slug, candidate.source, candidate.source_ref, weight, 0, None, created_at)
                )

                for res in research:
                    research_id = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO content_research (id, topic_id, url, title, summary)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (research_id, topic_id, res.url, res.title, res.summary)
                    )
                db.commit()

                return ContentTopic(
                    id=topic_id,
                    name=candidate.name,
                    slug=candidate.slug,
                    source=candidate.source,
                    source_ref=candidate.source_ref,
                    weight=weight,
                    used_count=0,
                    last_used_at=None,
                    created_at=created_at
                )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save topic {candidate.name}: {e}", exc_info=True)
            raise e
        finally:
            cur.close()
