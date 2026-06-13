"""Shared Bedrock text-generation helper for the content pipelines."""

import os
import logging
import asyncio
from typing import Optional, Tuple

import boto3

from private_internet.config import get_settings

logger = logging.getLogger(__name__)


def bedrock_text_region() -> str:
    """Region for the primary content TEXT model (Mistral Small) — it IS available
    in eu-central-1, so default to settings.aws_region. Override with
    BEDROCK_TEXT_REGION. (The Nova text fallback + Nova Canvas use the eu-west-1
    image region instead — see _bedrock_nova_region.)"""
    return os.getenv("BEDROCK_TEXT_REGION") or get_settings().aws_region


def _bedrock_nova_region() -> str:
    """Region for the Nova models (text fallback + Nova Canvas images). Nova is
    not in eu-central-1, so default to the eu-west-1 image region."""
    return os.getenv("BEDROCK_IMAGE_REGION") or "eu-west-1"


async def converse_text(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> Tuple[str, dict]:
    """
    Invoke Claude Haiku on Bedrock via the converse API, falling back to the
    configured general model on failure. Returns (text, usage) where usage is
    the converse `usage` dict ({inputTokens, outputTokens, totalTokens}).
    Raises if both models fail.
    """
    # Primary text model: Mistral Small (available in eu-central-1).
    model_id = os.getenv("BEDROCK_TEXT_MODEL_ID", "mistral.mistral-small-2402-v1:0")

    def invoke():
        kwargs = {
            "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
            "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]
        try:
            # Primary: Mistral Small in eu-central-1 (bedrock_text_region).
            client = boto3.client("bedrock-runtime", region_name=bedrock_text_region())
            response = client.converse(modelId=model_id, **kwargs)
        except Exception as e:
            logger.warning(f"Primary text model {model_id} failed: {e}. Trying Nova fallback.")
            # Fallback: Nova in eu-west-1.
            fallback_model = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
            client = boto3.client("bedrock-runtime", region_name=_bedrock_nova_region())
            response = client.converse(modelId=fallback_model, **kwargs)
        text = response["output"]["message"]["content"][0]["text"]
        usage = response.get("usage", {})
        return text, usage

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, invoke)
