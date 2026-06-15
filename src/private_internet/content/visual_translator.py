"""Visual scene translation layer for the SIGNAL video pipeline.

Kling / Veo3 want concrete, filmable scene descriptions — not the abstract
topic language the script generator produces ("a philosophical reflection on
the circular economy" is a terrible video prompt). This module is a SEPARATE
Bedrock Claude call (forced tool-use, temperature 0) that converts each topic /
script excerpt into concrete, camera-ready prompts.

It sits between script generation (Stage 2) and the Kling clip call (Stage 4).
The original topic text is NEVER sent to Kling directly — only the translated
prompts produced here, each with the house style suffix appended.
"""

import logging
from typing import List, Optional

from private_internet.content.llm import converse_tool

logger = logging.getLogger(__name__)


VISUAL_TRANSLATOR_SYSTEM = """
You are a cinematographer and visual director. You receive an abstract
topic or script excerpt and translate it into a concrete, filmable
scene description suitable for AI video generation.

Rules for your output:
- Describe only what the camera sees. No abstract concepts.
- Every scene must have: a subject, an action, a location, a lighting
  condition, and a camera movement or position.
- Use real-world specificity: "a man in his 30s" not "a person".
  "a Berlin flea market on a Sunday morning" not "a marketplace".
- Maximum 60 words per scene description.
- Write in present tense.
- Never mention brands, flags, logos, text, or recognisable public figures.
- Never describe violence, nudity, or politically sensitive imagery.
- Mood should be: cinematic, calm, human. 35mm film aesthetic.
  Shallow depth of field. Natural or practical lighting only.
- End every description with: camera movement instruction.
  Options: "Static shot." / "Slow push-in." / "Slow pull-back." /
  "Handheld, slight movement." / "Low angle, static."
""".strip()


VISUAL_TRANSLATOR_TOOL = {
    "name": "translate_to_visual_scene",
    "description": (
        "Return one concrete, filmable scene description per requested scene, "
        "translating abstract topic language into camera-ready Kling prompts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scene_descriptions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "scene_number": {"type": "integer"},
                        "kling_prompt": {
                            "type": "string",
                            "description": "Concrete, filmable, max 60 words",
                        },
                        "duration_seconds": {
                            "type": "integer",
                            "enum": [5, 8, 10],
                        },
                        "mood": {
                            "type": "string",
                            "enum": ["calm", "tense", "warm", "melancholic", "energetic"],
                        },
                    },
                    "required": [
                        "scene_number",
                        "kling_prompt",
                        "duration_seconds",
                        "mood",
                    ],
                },
            }
        },
        "required": ["scene_descriptions"],
    },
}


# Appended to every translated prompt before it reaches Kling/Veo3.
KLING_STYLE_SUFFIX = (
    "Photorealistic. 35mm film grain. Shallow depth of field. "
    "Natural or practical lighting only. No text. No logos. "
    "No CGI. Cinematic color grade, slightly desaturated."
)


def build_final_prompt(scene: dict) -> str:
    """The exact string sent to Kling: translated description + house style."""
    return f"{scene['kling_prompt']} {KLING_STYLE_SUFFIX}"


async def translate_scenes(
    *,
    topic: str,
    narration_script: str,
    total_scenes: int,
    target_duration_seconds: int,
) -> List[dict]:
    """Translate a topic + script excerpt into `total_scenes` concrete scenes.

    Returns the list of scene dicts (scene_number, kling_prompt,
    duration_seconds, mood), sorted by scene_number. Returns [] if the model
    produced no tool output — callers degrade to the slide fallback rather than
    sending abstract text to Kling.
    """
    user_message = (
        f"Topic: {topic}\n"
        f"Script excerpt: {narration_script[:200]}\n"
        f"Number of scenes needed: {total_scenes}\n"
        f"Total video duration target: {target_duration_seconds} seconds"
    )

    tool_input, _usage = await converse_tool(
        user_message,
        VISUAL_TRANSLATOR_TOOL,
        system_prompt=VISUAL_TRANSLATOR_SYSTEM,
        temperature=0.0,
        max_tokens=2048,
    )

    if not tool_input:
        logger.warning("Visual translator returned no tool output for topic=%r", topic[:80])
        return []

    scenes: List[dict] = tool_input.get("scene_descriptions") or []
    scenes = [s for s in scenes if isinstance(s, dict) and s.get("kling_prompt")]
    scenes.sort(key=lambda s: s.get("scene_number") or 0)
    return scenes


def kling_duration(scene: dict) -> int:
    """The clip length (seconds) to request for a scene.

    Returns the scene's requested ``duration_seconds`` verbatim (default 5). The
    fal call (``generate_video_clip``) snaps this to whatever the configured
    video model actually supports, so duration policy lives in one place — here
    we only express the intent.
    """
    requested: Optional[int] = scene.get("duration_seconds")
    return requested if isinstance(requested, int) and requested > 0 else 5
