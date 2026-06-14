"""Brain embedding backends.

The brain owns its embedding model so the memory store can run on any host
without depending on AWS Bedrock. Two backends, selected by EMBEDDING_BACKEND:

  - "bedrock" : legacy Amazon Titan Embed v2 (1024-d). Kept for back-compat and
                as the safe default during the migration.
  - "ollama"  : a local Ollama server (default bge-m3, 1024-d). Self-hosted — the
                target for both AWS and future user-owned hardware.

Both emit 1024-d vectors, so the `memories.embedding vector(1024)` column is
unchanged. Vectors from different models are NOT comparable, so switching
backends requires re-embedding every stored row (scripts/reembed_memories.py).
The model id is recorded per row (memories.embedding_model) so a mismatch is
detectable and a future model upgrade can re-embed only what it must.
"""

import json
import urllib.request

from private_internet.config import get_settings


class Embedder:
    """Embedding backend interface. `model_id` is stored alongside each vector."""

    model_id: str
    dim: int = 1024

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class BedrockTitanEmbedder(Embedder):
    """Amazon Titan Embed v2 via Bedrock (the legacy path)."""

    model_id = "amazon.titan-embed-text-v2:0"
    dim = 1024

    def embed(self, text: str) -> list[float]:
        import boto3  # local import: unused on the Bedrock-free path

        s = get_settings()
        client = boto3.client("bedrock-runtime", region_name=s.aws_region)
        resp = client.invoke_model(
            modelId=self.model_id,
            body=json.dumps({"inputText": text}),
        )
        return json.loads(resp["body"].read())["embedding"]


class OllamaEmbedder(Embedder):
    """Embeddings from a local Ollama server (POST /api/embed). Self-contained,
    so it runs identically on EC2 and on user hardware."""

    dim = 1024

    def __init__(self, url: str, model: str, timeout: float = 120.0):
        self._url = url.rstrip("/")
        self.model_id = model
        # Generous timeout: the first request after idle cold-loads the model
        # into RAM (~10s+, longer under memory pressure / swap). Warm calls are
        # sub-second. 30s was too low and killed cold loads on small hosts.
        self._timeout = timeout

    def embed(self, text: str) -> list[float]:
        req = urllib.request.Request(
            f"{self._url}/api/embed",
            data=json.dumps({"model": self.model_id, "input": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read())
        embeddings = data.get("embeddings")
        if not embeddings or not embeddings[0]:
            raise RuntimeError(
                f"Ollama returned no embedding for model {self.model_id!r}: {data}"
            )
        return embeddings[0]


def get_embedder() -> Embedder:
    """Return the active embedder per settings (EMBEDDING_BACKEND)."""
    s = get_settings()
    backend = (s.embedding_backend or "bedrock").lower()
    if backend == "ollama":
        return OllamaEmbedder(s.embedding_url, s.embedding_model)
    if backend == "bedrock":
        return BedrockTitanEmbedder()
    raise ValueError(
        f"Unknown EMBEDDING_BACKEND {backend!r} (expected 'bedrock' or 'ollama')"
    )
