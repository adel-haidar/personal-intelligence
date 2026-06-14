"""fal.ai image generation backend (FLUX) for PULSE post images + SIGNAL slides.

Replaces the retired Bedrock image models (Nova Canvas / Titan G2 are EOL'd /
legacy-revoked in this account). Calls fal.run synchronously over httpx (httpx
ships transitively with fastapi[standard]), then fetches the returned image URL
into raw bytes — the rest of the pipeline works with bytes. Callers keep their
gradient-slide fallback, so an unfunded balance or any error degrades gracefully.
"""

import httpx

from private_internet.config import get_settings

_FAL_BASE = "https://fal.run/"


async def generate_image(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    *,
    negative_text: str = "",
) -> bytes:
    """Generate one image via fal.ai and return its bytes. Raises on failure."""
    s = get_settings()
    if not s.fal_api_key:
        raise RuntimeError("FAL_AI_API_KEY not configured")

    model = s.fal_image_model
    body: dict = {
        "prompt": prompt,
        "image_size": {"width": width, "height": height},
        "num_images": 1,
    }
    # schnell is a 1–4 step distilled model — keep steps low for cost/speed.
    if "schnell" in model:
        body["num_inference_steps"] = 4
    headers = {"Authorization": f"Key {s.fal_api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{_FAL_BASE}{model}", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        images = data.get("images") or []
        if not images or not images[0].get("url"):
            raise RuntimeError(f"fal.ai returned no image: {str(data)[:200]}")
        img = await client.get(images[0]["url"])
        img.raise_for_status()
        return img.content
