import logging

logger = logging.getLogger(__name__)


class BaseLLMService:
    """Base class for any service that needs to talk to an LLM via Amazon Bedrock.

    `EmailAssessor` and `EmailResponseWriter` both extend this class. It handles
    the low-level details of sending a prompt and getting a text response back,
    so the subclasses only need to worry about what to ask and how to parse the answer.
    """

    def __init__(self, bedrock_client, model_id: str):
        """Store the Bedrock client and the model to use for all requests.

        Args:
            bedrock_client: A boto3 `bedrock-runtime` client, already configured
                with the correct AWS region and credentials.
            model_id: The Bedrock model identifier string, e.g.
                'eu.amazon.nova-2-lite-v1:0'.
        """
        self._client = bedrock_client
        self._model_id = model_id

    def _invoke(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> str:
        """Send a prompt to the LLM and return the raw text response.

        This wraps Bedrock's `converse` API, which works like a single-turn
        chat: we send one user message and get one assistant reply back.

        Args:
            prompt: The full instruction text to send to the model.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature. Pass 0.0 for fully deterministic
                output. When None, the model's default is used.

        Returns:
            The model's response as a plain string.
        """
        logger.debug("Invoking Bedrock model %s (temperature=%s)", self._model_id, temperature)
        inference_config: dict = {"maxTokens": max_tokens}
        if temperature is not None:
            inference_config["temperature"] = temperature
        response = self._client.converse(
            modelId=self._model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig=inference_config,
        )
        return response["output"]["message"]["content"][0]["text"]

    def _strip_markdown(self, text: str) -> str:
        """Extract the outermost JSON object from a model response.

        Handles markdown code fences and any prose the model adds before or
        after the JSON block by slicing from the first '{' to the last '}'.
        """
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.removesuffix("```").strip()
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
        return text.strip()
