"""Thin Bedrock `converse` helper with a cached system prompt.

The large static instruction prompts in `prompts.py` are sent as a Bedrock
`system` block followed by a `cachePoint`, so Bedrock caches the encoded prompt
and reuses it across the orchestrate -> draft -> evaluate -> revise calls. If the
configured model does not support prompt caching, we transparently retry without
the cache point so generation still works.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Remember per-model whether cachePoint is unsupported, so we stop paying the
# failed-first-call cost on every subsequent invocation in this process.
_CACHE_UNSUPPORTED: set[str] = set()


def converse_cached(
    client,
    model_id: str,
    system_prompt: str,
    user_text: str,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> str:
    """Single-turn converse with a cached system prompt. Returns the reply text."""
    inference_config = {"maxTokens": max_tokens, "temperature": temperature}
    messages = [{"role": "user", "content": [{"text": user_text}]}]

    if model_id not in _CACHE_UNSUPPORTED:
        try:
            resp = client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}, {"cachePoint": {"type": "default"}}],
                messages=messages,
                inferenceConfig=inference_config,
            )
            return resp["output"]["message"]["content"][0]["text"]
        except Exception as exc:  # noqa: BLE001 — fall back on any caching-related error
            logger.info(
                "Prompt caching unavailable for %s (%s) — retrying without cachePoint",
                model_id, type(exc).__name__,
            )
            _CACHE_UNSUPPORTED.add(model_id)

    resp = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig=inference_config,
    )
    return resp["output"]["message"]["content"][0]["text"]


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract the outermost JSON object from a model response.

    Tolerates markdown fences and surrounding prose. Returns {} if no object is
    found or it doesn't parse.
    """
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start:end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Could not parse JSON object from model output: %r", raw[:200])
        return {}
