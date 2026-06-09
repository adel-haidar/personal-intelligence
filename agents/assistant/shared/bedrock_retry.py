import logging

logger = logging.getLogger(__name__)


def invoke_with_tool_retry(
    client,
    model_id: str,
    system_prompt: str,
    messages: list[dict],
    tool_spec: dict,
    max_tokens: int = 8192,
    max_retries: int = 2,
) -> dict:
    """Call Bedrock converse with tool_use forced. Returns the tool input dict.

    If Claude returns text instead of calling the tool, appends a correction
    turn and retries up to max_retries times. Raises ValueError after exhausting
    all attempts so failures are loud, not silent.
    """
    tool_name = tool_spec["name"]
    messages = list(messages)

    for attempt in range(max_retries + 1):
        response = client.converse(
            modelId=model_id,
            system=[{"text": system_prompt}],
            messages=messages,
            toolConfig={
                "tools": [{"toolSpec": tool_spec}],
                "toolChoice": {"tool": {"name": tool_name}},
            },
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
        )

        content = response["output"]["message"]["content"]
        tool_block = next((b for b in content if "toolUse" in b), None)

        if tool_block:
            return tool_block["toolUse"]["input"]

        logger.warning(
            "Bedrock returned no tool_use on attempt %d/%d — retrying with pressure",
            attempt + 1,
            max_retries + 1,
        )
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": [{"text": "You must call the provided tool. Do not respond with text. Call the tool now."}],
        })

    raise ValueError(
        f"Bedrock failed to return tool_use after {max_retries + 1} attempts"
    )
