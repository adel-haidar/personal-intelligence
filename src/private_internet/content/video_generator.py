"""Video script + slide image generation for the SIGNAL pipeline (Phase 4, Tasks 1–2).

Two script generators live here:
  - VideoScriptGenerator   — the legacy 5-section short script (slide-based videos)
  - SceneScriptGenerator   — the scene-by-scene breakdown for long-form
                             scene-stitching (SIGNAL 3–5 min, STORIES 6–45 min)
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from private_internet.content.llm import converse_text, converse_tool
from private_internet.content.image_generator import PostImageGenerator

logger = logging.getLogger(__name__)

SECTION_IDS = ["INTRO", "SECTION_1", "SECTION_2", "SECTION_3", "OUTRO"]

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720

# SIGNAL long-form duration target (seconds). STORIES targets live in
# content/stories/generator.py.
SIGNAL_DURATION_TARGETS = {
    "short": (32, 48),               # ~4–6 clips — cheap real video for the feed
    "standard": (180, 300),          # 3–5 minutes
}

# Roughly 8-second clips, so a 3–5 min SIGNAL video is ~22–38 scenes.
_SCENE_SECONDS = 8


# Scene-by-scene script tool — forced on the Bedrock call. One scene ≈ 8 seconds;
# narration_text is the spoken line for that scene, visual_description is the
# abstract beat (translated to a Kling prompt separately by the assembler).
SCRIPT_WITH_SCENES_TOOL = {
    "name": "generate_video_script",
    "description": "Generate a scene-by-scene video script for scene-stitched assembly",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "total_duration_seconds": {
                "type": "integer",
                "description": "Target total duration in seconds",
            },
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "scene_number": {"type": "integer"},
                        "narration_text": {
                            "type": "string",
                            "description": "The spoken narration for this scene "
                                           "only. Will be passed to ElevenLabs.",
                        },
                        "visual_description": {
                            "type": "string",
                            "description": "Abstract description of what this "
                                           "scene is about. Will be translated "
                                           "to a Kling prompt separately.",
                        },
                        "duration_seconds": {
                            "type": "integer",
                            "description": "Target duration for this scene's clip",
                        },
                        "scene_type": {
                            "type": "string",
                            "enum": [
                                "establishing",
                                "development",
                                "transition",
                                "climax",
                                "resolution",
                            ],
                        },
                    },
                    "required": ["scene_number", "narration_text",
                                 "visual_description", "duration_seconds",
                                 "scene_type"],
                },
            },
        },
        "required": ["title", "total_duration_seconds", "scenes"],
    },
}


@dataclass
class ScriptSection:
    id: str
    text: str
    image_prompt: str
    heading: str = ""  # short on-screen slide title (distinct per section)


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
                {"id": s.id, "text": s.text, "image_prompt": s.image_prompt, "heading": s.heading}
                for s in self.sections
            ],
        })


@dataclass
class SceneScript:
    """A scene-by-scene breakdown for long-form scene-stitched assembly."""
    title: str
    total_duration_seconds: int
    scenes: List[dict]   # each: scene_number, narration_text, visual_description,
                         #       duration_seconds, scene_type

    @property
    def narration_text(self) -> str:
        """Full narration: every scene's spoken line joined in order."""
        return " ".join(
            (s.get("narration_text") or "").strip()
            for s in self.scenes
            if (s.get("narration_text") or "").strip()
        )


class SceneScriptGenerator:
    """Generates a scene-by-scene script via a forced Bedrock Claude tool call.

    Shared by SIGNAL (3–5 min) and STORIES (6–45 min) — only the duration target
    and scene count differ, passed in by the caller.
    """

    async def generate(
        self,
        topic: dict,
        creator: dict,
        research: List[dict],
        *,
        duration_min: int,
        duration_max: int,
        content_label: str = "video",
    ) -> SceneScript:
        research_text = "\n".join(
            f"- {r.get('title') or 'Untitled'}: {r.get('summary') or ''} ({r.get('url')})"
            for r in research[:5]
        ) or "(no research available)"

        # ~8s per scene → derive the expected scene count from the duration band.
        min_scenes = max(1, duration_min // _SCENE_SECONDS)
        max_scenes = max(min_scenes, duration_max // _SCENE_SECONDS)

        system_prompt = (
            f"{creator['style_prompt']}\n\n"
            f"You are writing a {content_label} as a scene-by-scene breakdown for "
            "automated video assembly. Each scene becomes one short (~8 second) "
            "generated video clip plus its own narration line.\n\n"
            "Rules:\n"
            f"- Produce between {min_scenes} and {max_scenes} scenes, each about "
            f"{_SCENE_SECONDS} seconds long.\n"
            "- narration_text is spoken aloud by an English TTS voice — write it "
            "ENTIRELY in English, in the persona's tone, one or two sentences.\n"
            "- visual_description is an abstract beat (mood, subject, action) — it "
            "is translated into a video prompt separately, so do NOT write camera "
            "directions or text overlays.\n"
            "- Number scenes sequentially from 1.\n"
            "- Use scene_type to shape the arc: open with 'establishing', build "
            "through 'development'/'transition', peak at 'climax', close with "
            "'resolution'.\n"
            "Call generate_video_script with the full breakdown."
        )

        user_prompt = (
            f"Topic: {topic['name']}\n"
            f"Research:\n{research_text}\n\n"
            f"Generate a script with total_duration_seconds between "
            f"{duration_min} and {duration_max}."
        )

        result, _ = await converse_tool(
            user_prompt=user_prompt,
            tool=SCRIPT_WITH_SCENES_TOOL,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=8192,
        )
        if not result or not result.get("scenes"):
            raise ValueError("Scene script generation returned no scenes")

        scenes = result["scenes"]
        # Defensive: ensure sequential scene_number and a positive duration so the
        # assembler's ordering / fallback-card sizing always has valid inputs.
        for i, scene in enumerate(scenes, start=1):
            scene.setdefault("scene_number", i)
            if not scene.get("duration_seconds"):
                scene["duration_seconds"] = _SCENE_SECONDS

        return SceneScript(
            title=result.get("title") or topic["name"],
            total_duration_seconds=int(
                result.get("total_duration_seconds")
                or sum(s["duration_seconds"] for s in scenes)
            ),
            scenes=scenes,
        )


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
            "Write the narration ENTIRELY in English — it is read aloud by an "
            "English text-to-speech voice. Keep the persona's tone, but do not "
            "include words or phrases in other languages.\n\n"
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
            '    {"id": "INTRO", "heading": str, "text": str, "image_prompt": str},\n'
            '    {"id": "SECTION_1", "heading": str, "text": str, "image_prompt": str},\n'
            '    {"id": "SECTION_2", "heading": str, "text": str, "image_prompt": str},\n'
            '    {"id": "SECTION_3", "heading": str, "text": str, "image_prompt": str},\n'
            '    {"id": "OUTRO", "heading": str, "text": str, "image_prompt": str}\n'
            "  ],\n"
            '  "description": str\n'
            "}\n"
            "heading is a punchy 2–5 word on-screen slide title that captures that "
            "section's point (distinct per section). "
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
            ScriptSection(
                id=s["id"],
                text=s["text"],
                image_prompt=s["image_prompt"],
                heading=s.get("heading", ""),
            )
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


# Per-section top-of-gradient colors so consecutive slides look distinct
# (all dark + calm, bottom is always near-black). Keyed by section index.
_SLIDE_TOP_COLORS = [
    (28, 27, 46),   # indigo
    (20, 34, 46),   # deep teal
    (40, 24, 42),   # plum
    (24, 30, 48),   # slate blue
    (22, 38, 34),   # deep green
]


def _fallback_slide(
    width: int, height: int, title: str, subtitle: str = "", variant: int = 0
) -> bytes:
    """Render a calm gradient title-slide as PNG bytes.

    Used when no Bedrock image-generation model is available (every Amazon
    text-to-image model is retired and no Stability text-to-image model is
    invokable) so SIGNAL videos still render. Real AI images return
    automatically the moment a generator is configured. `variant` shifts the
    gradient color so consecutive slides differ. PIL is imported lazily so the
    module still imports on hosts without Pillow."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    # vertical gradient: a per-slide dark tint -> near-black (Calm Intelligence)
    top, bottom = _SLIDE_TOP_COLORS[variant % len(_SLIDE_TOP_COLORS)], (12, 12, 20)
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        column.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = column.resize((width, height))
    draw = ImageDraw.Draw(img)

    def _font(size: int, bold: bool = True):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for path in (
            f"/usr/share/fonts/truetype/dejavu/{name}",  # Debian/Ubuntu
            f"/usr/share/fonts/TTF/{name}",              # Arch
            f"/usr/share/fonts/dejavu/{name}",           # Fedora
            name,
        ):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default(size=size)  # Pillow >= 10.1 scalable default
        except TypeError:
            return ImageFont.load_default()

    title_font = _font(int(height * 0.075), bold=True)
    sub_font = _font(int(height * 0.035), bold=False)

    # word-wrap the title to ~80% of the slide width (max 4 lines)
    max_w = int(width * 0.8)
    lines, current = [], ""
    for word in (title or "").split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=title_font) <= max_w:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    lines = lines[:4] or [" "]

    line_h = int(height * 0.10)
    block_top = (height - line_h * len(lines)) // 2 - int(height * 0.03)
    y = block_top
    for line in lines:
        w_line = draw.textlength(line, font=title_font)
        draw.text(((width - w_line) / 2, y), line, font=title_font, fill=(228, 228, 240))
        y += line_h

    # amber accent dot + creator subtitle
    cx = width // 2
    draw.ellipse([cx - 5, y + 14, cx + 5, y + 24], fill=(232, 164, 68))
    if subtitle:
        w_sub = draw.textlength(subtitle, font=sub_font)
        draw.text(((width - w_sub) / 2, y + 36), subtitle, font=sub_font, fill=(232, 164, 68))

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class VideoImageGenerator(PostImageGenerator):
    """Reuses the Nova Canvas invoker from PostImageGenerator with 16:9 video sizing.

    When no image-generation model is reachable, each slide falls back to a
    rendered gradient title-slide so the video still assembles."""

    NEGATIVE_TEXT = "text, watermark, logo, people's faces, blurry"

    async def generate_for_section(
        self, section: ScriptSection, creator: dict, title: str = "", index: int = 0
    ) -> bytes:
        prompt = section.image_prompt + " cinematic, 16:9, dark editorial style, no text"
        try:
            return await self._generate_image(
                prompt,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT,
                negative_text=self.NEGATIVE_TEXT,
            )
        except Exception as exc:
            logger.warning(
                f"Slide image generation failed ({type(exc).__name__}); "
                "using gradient fallback slide."
            )
            # Each slide gets its own heading + tint so the video doesn't look
            # like one static frame.
            caption = section.heading or title or section.text[:60]
            return _fallback_slide(
                VIDEO_WIDTH, VIDEO_HEIGHT, caption, creator.get("name", ""), variant=index
            )

    async def generate_thumbnail(self, script: VideoScript, creator: dict) -> bytes:
        intro = script.sections[0]
        prompt = intro.image_prompt + " bold title overlay style, high contrast"
        try:
            return await self._generate_image(
                prompt,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT,
                negative_text=self.NEGATIVE_TEXT,
            )
        except Exception as exc:
            logger.warning(
                f"Thumbnail generation failed ({type(exc).__name__}); "
                "using gradient fallback slide."
            )
            return _fallback_slide(VIDEO_WIDTH, VIDEO_HEIGHT, script.title, creator.get("name", ""))
