"""Post image generation via Bedrock Nova Canvas (Phase 3, Task 3)."""

import os
import json
import base64
import logging
import asyncio
from typing import Tuple

import boto3

from private_internet.config import get_settings
from private_internet.content.llm import converse_text

logger = logging.getLogger(__name__)

# Nova Canvas is NOT available in eu-central-1 — eu-west-1 (Ireland) is the
# closest region that has it. Override with BEDROCK_IMAGE_REGION if needed.
_DEFAULT_IMAGE_REGION = "eu-west-1"


class PostImageGenerator:
    async def generate_for_post(
        self,
        topic: dict,
        creator: dict,
        post_body: str,
    ) -> Tuple[bytes, str]:
        """
        Generate an image for a post: Haiku writes the image prompt,
        Nova Canvas renders it. Returns (image_bytes, image_prompt).
        """
        image_prompt = await self._generate_image_prompt(topic, creator, post_body)
        image_bytes = await self._generate_image(image_prompt)
        return image_bytes, image_prompt

    async def _generate_image_prompt(self, topic: dict, creator: dict, post_body: str) -> str:
        system_prompt = (
            "Generate a single image prompt for a social media post image.\n"
            "Style: dark, editorial, high-contrast. No text in image.\n"
            f"Creator aesthetic: {(creator.get('style_prompt') or '')[:100]}\n"
            "Output ONLY the image prompt, 1–2 sentences."
        )
        user_prompt = f"Topic: {topic['name']}. Post excerpt: {post_body[:150]}"
        text, _ = await converse_text(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=256,
        )
        return text.strip()

    async def _generate_image(
        self,
        image_prompt: str,
        width: int = 1024,
        height: int = 1024,
        negative_text: str = "text, watermark, logo, blurry, low quality",
    ) -> bytes:
        """Dispatch to the configured image backend. fal.ai is the active default
        (Bedrock image models are EOL'd here); callers keep a gradient fallback."""
        settings = get_settings()
        if (settings.image_backend or "fal").lower() == "fal":
            from private_internet.content.fal_image import generate_image
            return await generate_image(
                image_prompt, width, height, negative_text=negative_text
            )
        return await self._invoke_nova_canvas(
            image_prompt, width=width, height=height, negative_text=negative_text
        )

    async def _invoke_nova_canvas(
        self,
        image_prompt: str,
        width: int = 1024,
        height: int = 1024,
        negative_text: str = "text, watermark, logo, blurry, low quality",
    ) -> bytes:
        settings = get_settings()
        region = os.getenv("BEDROCK_IMAGE_REGION", _DEFAULT_IMAGE_REGION) or settings.aws_region
        model_id = os.getenv("NOVA_CANVAS_MODEL_ID", "amazon.nova-canvas-v1:0")

        request_body = {
            "taskType": "TEXT_IMAGE",
            "textToImageParams": {
                "text": image_prompt,
                "negativeText": negative_text,
            },
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "height": height,
                "width": width,
                "quality": "standard",  # standard, not premium, to save cost
            },
        }

        def invoke():
            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json",
            )
            payload = json.loads(response["body"].read())
            images = payload.get("images") or []
            if not images:
                raise RuntimeError(f"Nova Canvas returned no images: {payload.get('error')}")
            return base64.b64decode(images[0])

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, invoke)
