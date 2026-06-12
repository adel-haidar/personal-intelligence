import os
import json
import logging
import asyncio
import re
from dataclasses import dataclass
from typing import List, Tuple

import google.generativeai as genai
import boto3
from personal_intelligence.config import get_settings
from personal_intelligence.content.topic_intelligence import TopicCandidate

logger = logging.getLogger(__name__)


@dataclass
class ResearchResult:
    url: str
    title: str
    summary: str


class WebResearchService:
    def __init__(self):
        # Configure Gemini API key from environment variable
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY environment variable is not set.")
        genai.configure(api_key=api_key)
        
        # Configure the generative model with Google Search retrieval enabled
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            tools=[{"google_search_retrieval": {}}]
        )

    async def research_topic(self, topic: TopicCandidate) -> List[ResearchResult]:
        """
        Research the topic using Gemini 2.0 Flash with Google Search Grounding.
        Returns a list of ResearchResult objects.
        """
        prompt = (
            f"Research the topic: '{topic.name}'\n\n"
            "Find:\n"
            "1. 3–5 authoritative articles or sources published in the last 6 months\n"
            "2. For each: title, URL, and a 2-sentence neutral summary\n"
            "3. Key statistics or data points if available\n"
            "4. Any controversy or opposing viewpoints\n\n"
            "Output ONLY a JSON array of objects:\n"
            '[{ "url": str, "title": str, "summary": str }]\n'
            "Do not output any introductory or concluding text, nor markdown fences (like ```json). Just the raw JSON."
        )

        loop = asyncio.get_event_loop()
        
        def generate_content():
            return self.model.generate_content(prompt)

        try:
            response = await loop.run_in_executor(None, generate_content)
        except Exception as e:
            logger.error(f"Gemini content generation failed: {e}", exc_info=True)
            return []

        response_text = response.text.strip() if response and hasattr(response, "text") else ""

        # Clean JSON markdown blocks if the model included them
        clean_text = response_text
        if clean_text.startswith("```"):
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            else:
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

        results = []
        try:
            if clean_text:
                data_list = json.loads(clean_text)
                for item in data_list:
                    results.append(ResearchResult(
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        summary=item.get("summary", "")
                    ))
        except Exception as e:
            logger.warning(f"Failed to parse JSON text from Gemini research: '{response_text}'. Error: {e}")

        # Parse grounding metadata from response candidates
        grounding_sources: List[Tuple[str, str]] = []
        try:
            if response and hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
                    metadata = candidate.grounding_metadata
                    if hasattr(metadata, "grounding_chunks") and metadata.grounding_chunks:
                        for chunk in metadata.grounding_chunks:
                            if hasattr(chunk, "web") and chunk.web:
                                uri = chunk.web.uri
                                title = chunk.web.title
                                if uri:
                                    grounding_sources.append((uri, title))
        except Exception as e:
            logger.warning(f"Failed to parse grounding metadata: {e}")

        # Fallback: if we failed to get structured results from the text, but have grounding URLs, use them!
        if not results and grounding_sources:
            logger.info("Using fallback grounding metadata sources for research results")
            for url, title in grounding_sources:
                # Deduplicate by url
                if not any(r.url == url for r in results):
                    results.append(ResearchResult(
                        url=url,
                        title=title or "Cited Source",
                        summary=f"Resource cited during Google Search Grounding for topic: '{topic.name}'."
                    ))

        return results

    async def assess_topic_relevance(self, topic: TopicCandidate, research: List[ResearchResult]) -> float:
        """
        Returns a relevance weight (0.0-1.0) using Claude Haiku on Bedrock.
        Assess factors like user interests, trending state, and suitability for script generation.
        """
        research_text = ""
        for r in research:
            research_text += f"- Title: {r.title}\n  URL: {r.url}\n  Summary: {r.summary}\n"

        prompt = (
            "You are a relevance assessment model. Review the following topic candidate and associated research results.\n"
            "Determine the overall relevance weight (from 0.0 to 1.0) for the user based on:\n"
            "- Is the topic currently trending or highly relevant?\n"
            "- Does it connect to the user's known interests (such as job relocation to Switzerland, AWS certification, weight loss, history, etc.)?\n"
            "- Is there enough material for a good video script?\n\n"
            f"Topic: {topic.name}\n"
            f"Keywords: {', '.join(topic.keywords)}\n"
            f"Research:\n{research_text}\n\n"
            "Output ONLY a single floating-point number between 0.0 and 1.0 (e.g., 0.75). Do not include any other text, reasoning, or markdown formatting."
        )

        settings = get_settings()
        model_id = os.getenv("BEDROCK_HAIKU_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
        
        loop = asyncio.get_event_loop()
        
        def invoke_bedrock():
            client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
            try:
                response = client.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"temperature": 0.0}
                )
                return response["output"]["message"]["content"][0]["text"]
            except Exception as e:
                logger.warning(f"Failed to call Bedrock Haiku for relevance assessment: {e}. Trying fallback.")
                fallback_model = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
                response = client.converse(
                    modelId=fallback_model,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"temperature": 0.0}
                )
                return response["output"]["message"]["content"][0]["text"]

        try:
            response_text = await loop.run_in_executor(None, invoke_bedrock)
            response_text = response_text.strip()
        except Exception as e:
            logger.error(f"Bedrock relevance assessment failed completely: {e}", exc_info=True)
            return 0.5

        try:
            match = re.search(r"(\d+\.\d+|\d+)", response_text)
            if match:
                weight = float(match.group(1))
                return max(0.0, min(1.0, weight))
            return 0.5
        except Exception as e:
            logger.error(f"Failed to parse weight float from Bedrock response: '{response_text}'. Error: {e}")
            return 0.5
