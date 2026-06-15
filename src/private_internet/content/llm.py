"""Shared Bedrock text-generation helper for the content pipelines."""

import os
import logging
import asyncio
from typing import Optional, Tuple

import boto3

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

# Forced tool_choice needs a model that supports it. Mistral/Pixtral do NOT, and
# the Anthropic Claude models on Bedrock require an AWS Marketplace agreement
# (the Haiku 4.5 one expired 2026-06-15 → AccessDenied). Amazon Nova is
# first-party (no agreement), enabled in eu-central-1, and supports forced tools,
# so it is the safe default. Override per-instance with BEDROCK_PULSE_MODEL_ID.
PULSE_MODEL_DEFAULT = "eu.amazon.nova-pro-v1:0"


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
    # Primary text model: Amazon Nova Pro (first-party, eu-central-1, no
    # Marketplace agreement). Override with BEDROCK_TEXT_MODEL_ID.
    model_id = os.getenv("BEDROCK_TEXT_MODEL_ID", "eu.amazon.nova-pro-v1:0")

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
            # Fallback: Nova Lite in eu-west-1.
            fallback_model = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-lite-v1:0")
            client = boto3.client("bedrock-runtime", region_name=_bedrock_nova_region())
            response = client.converse(modelId=fallback_model, **kwargs)
        text = response["output"]["message"]["content"][0]["text"]
        usage = response.get("usage", {})
        return text, usage

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, invoke)


async def converse_tool(
    user_prompt: str,
    tool: dict,
    *,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    model_id: Optional[str] = None,
) -> Tuple[Optional[dict], dict]:
    """
    Invoke a Claude model on Bedrock with a single FORCED tool (toolChoice).
    Returns (tool_input, usage) where tool_input is the model's structured
    arguments for the tool, or None if no toolUse block came back.

    `tool` is in Anthropic-native shape: {"name", "description", "input_schema"}.
    It is adapted to the Bedrock converse `toolSpec` format here.
    """
    model = model_id or os.getenv("BEDROCK_PULSE_MODEL_ID", PULSE_MODEL_DEFAULT)

    def invoke():
        client = boto3.client("bedrock-runtime", region_name=bedrock_text_region())
        kwargs = {
            "modelId": model,
            "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
            "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
            "toolConfig": {
                "tools": [{"toolSpec": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": {"json": tool["input_schema"]},
                }}],
                "toolChoice": {"tool": {"name": tool["name"]}},
            },
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]
        response = client.converse(**kwargs)
        usage = response.get("usage", {})
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block:
                return block["toolUse"]["input"], usage
        return None, usage

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, invoke)
