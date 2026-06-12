"""Video script + slide image generation for the SIGNAL pipeline (Phase 4, Tasks 1–2)."""

import json
import logging
from dataclasses import dataclass
from typing import List

from personal_intelligence.content.llm import converse_text
from personal_intelligence.content.image_generator import PostImageGenerator

logger = logging.getLogger(__name__)

SECTION_IDS = ["INTRO", "SECTION_1", "SECTION_2", "SECTION_3", "OUTRO"]

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720


@dataclass
class ScriptSection:
    id: str
    text: str
    image_prompt: str


@dataclass
class VideoScript:
    title: str
    description: str
    sections: List[ScriptSection]  # always 5: INTRO, SECTION_1..3, OUTRO

    def to_json(self) -> str:
        return json.dumps({
            "title": self.title,
            "description": self.description,
            "sections": [
                {"id": s.id, "text": s.text, "image_prompt": s.image_prompt}
                for s in self.sections
            ],
        })


def _strip_markdown_fences(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean[7:] if clean.startswith("```json") else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    return clean


class VideoScriptGenerator:
    """Generates a structured 5-section narration script via Bedrock Claude Haiku."""

    async def generate(self, topic: dict, creator: dict, research: List[dict]) -> VideoScript:
        """
        topic / creator: row dicts from content_topics / content_creators.
        research: row dicts from content_research ({url, title, summary}).
        """
        research_text = "\n".join(
            f"- {r.get('title') or 'Untitled'}: {r.get('summary') or ''} ({r.get('url')})"
            for r in research[:5]
        ) or "(no research available)"

        system_prompt = (
            f"{creator['style_prompt']}\n\n"
            "You are writing a narration script for a short video "
            "(90–120 seconds spoken at normal pace ≈ 150 words/minute, "
            "so target 225–300 words total).\n\n"
            "Structure EXACTLY:\n"
            "- INTRO (1 sentence hook, 15–20 words)\n"
            "- SECTION_1: first key point (60–80 words)\n"
            "- SECTION_2: second key point (60–80 words)\n"
            "- SECTION_3: third key point or counterpoint (60–80 words)\n"
            "- OUTRO (closing thought + 1 relevant URL if available, 20–30 words)\n\n"
            "Use research facts where relevant. Cite URLs naturally "
            "('according to Reuters...' style).\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            '  "title": str,\n'
            '  "sections": [\n'
            '    {"id": "INTRO", "text": str, "image_prompt": str},\n'
            '    {"id": "SECTION_1", "text": str, "image_prompt": str},\n'
            '    {"id": "SECTION_2", "text": str, "image_prompt": str},\n'
            '    {"id": "SECTION_3", "text": str, "image_prompt": str},\n'
            '    {"id": "OUTRO", "text": str, "image_prompt": str}\n'
            "  ],\n"
            '  "description": str\n'
            "}\n"
            "description is a 2-sentence video description. "
            "No preamble, no markdown fences."
        )

        user_prompt = f"Topic: {topic['name']}\nResearch:\n{research_text}"

        text, _ = await converse_text(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=2048,
        )
        data = json.loads(_strip_markdown_fences(text))

        sections = [
            ScriptSection(id=s["id"], text=s["text"], image_prompt=s["image_prompt"])
            for s in data["sections"]
        ]
        section_ids = [s.id for s in sections]
        if section_ids != SECTION_IDS:
            raise ValueError(f"Script sections out of spec: {section_ids}")

        return VideoScript(
            title=data["title"],
            description=data["description"],
            sections=sections,
        )


class VideoImageGenerator(PostImageGenerator):
    """Reuses the Nova Canvas invoker from PostImageGenerator with 16:9 video sizing."""

    NEGATIVE_TEXT = "text, watermark, logo, people's faces, blurry"

    async def generate_for_section(self, section: ScriptSection, creator: dict) -> bytes:
        prompt = section.image_prompt + " cinematic, 16:9, dark editorial style, no text"
        return await self._invoke_nova_canvas(
            prompt,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            negative_text=self.NEGATIVE_TEXT,
        )

    async def generate_thumbnail(self, script: VideoScript, creator: dict) -> bytes:
        intro = script.sections[0]
        prompt = intro.image_prompt + " bold title overlay style, high contrast"
        return await self._invoke_nova_canvas(
            prompt,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            negative_text=self.NEGATIVE_TEXT,
        )
