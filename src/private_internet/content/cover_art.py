"""Resilient cover / thumbnail generation for ALL generated content.

Every generated post (PULSE), song (ARIA), video (SIGNAL), and film (STORIES)
wants a cover image. The primary backend is fal.ai FLUX (``content/fal_image.py``),
but it fails whenever the fal balance is unfunded — and historically that left
PULSE posts and ARIA tracks with **no image at all** (``image_url`` / ``art_key``
NULL), while SIGNAL/STORIES fell back to a flat gradient.

This module guarantees a cover ALWAYS exists. ``generate_cover`` tries the
configured remote backend and, on ANY failure, renders a *designed*, on-brand
fallback locally with Pillow — no network, no paid API. The fallback is
deterministic per ``seed`` (the same track/post always gets the same cover),
mood-tinted from a curated palette, and carries a module kicker + title so it
reads as intentional design, not an error state.

Brand: "Calm Intelligence" — deep tinted gradients, no hard shadows, and the
signature amber **Brain Pulse** (4 orbiting dots). Pillow is imported lazily so
this module still imports on hosts without it.
"""

import hashlib
import logging
from typing import Tuple

from private_internet.config import get_settings

logger = logging.getLogger(__name__)

# Signature amber accent (Calm Intelligence "Brain Pulse"). Kept constant across
# palettes so the brand mark is recognisable regardless of the mood tint.
_BRAND_AMBER = (232, 164, 68)

_DEFAULT_NEGATIVE = "text, watermark, logo, blurry, low quality"

# Curated mood palettes: (top, bottom) gradient endpoints + a glow accent. All
# deep + desaturated to match the dark-default design system. A cover's palette
# is chosen deterministically from its seed, so it is stable across regenerations.
_PALETTES: Tuple[dict, ...] = (
    {"top": (38, 32, 74), "bottom": (12, 12, 22), "accent": (96, 84, 196)},   # indigo
    {"top": (20, 44, 52), "bottom": (10, 16, 20), "accent": (64, 150, 158)},  # teal
    {"top": (52, 26, 54), "bottom": (18, 12, 20), "accent": (158, 84, 150)},  # plum
    {"top": (50, 38, 24), "bottom": (18, 14, 10), "accent": (190, 132, 60)},  # amber-dark
    {"top": (22, 42, 32), "bottom": (10, 18, 14), "accent": (74, 150, 104)},  # forest
    {"top": (50, 24, 30), "bottom": (18, 10, 12), "accent": (170, 70, 78)},   # wine
    {"top": (24, 34, 56), "bottom": (10, 14, 22), "accent": (80, 120, 190)},  # steel blue
    {"top": (40, 40, 48), "bottom": (14, 14, 18), "accent": (140, 140, 150)}, # graphite
)


def _pick_palette(seed: str) -> dict:
    """Deterministically map a seed string to one of the mood palettes."""
    digest = hashlib.sha1((seed or "").encode("utf-8")).digest()
    return _PALETTES[digest[0] % len(_PALETTES)]


def _load_font(size: int, bold: bool = True):
    from PIL import ImageFont

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


def render_cover(
    width: int,
    height: int,
    *,
    title: str,
    kicker: str = "",
    subtitle: str = "",
    seed: str = "",
) -> bytes:
    """Render a designed, on-brand cover as PNG bytes — no network, never raises.

    A diagonal mood gradient + soft radial glow + the amber Brain Pulse motif +
    a kicker (e.g. ``PULSE``/``ARIA``/``SIGNAL``/``STORIES``), the wrapped title,
    and an optional subtitle. Deterministic in ``seed`` (falls back to ``title``).
    """
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFilter

    palette = _pick_palette(seed or title)
    top, bottom, accent = palette["top"], palette["bottom"], palette["accent"]

    # 1. Diagonal gradient, computed cheap at low res then upscaled (BILINEAR).
    gw, gh = max(2, width // 6), max(2, height // 6)
    grad = Image.new("RGB", (gw, gh))
    gpx = grad.load()
    max_d = (gw - 1) + (gh - 1)
    for yy in range(gh):
        for xx in range(gw):
            t = (xx + yy) / max_d
            gpx[xx, yy] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    img = grad.resize((width, height), Image.BILINEAR)

    # 2. Soft radial glow in the accent colour, off-centre toward the top.
    glow = Image.new("L", (gw, gh), 0)
    gd = ImageDraw.Draw(glow)
    cx, cy = int(gw * 0.5), int(gh * 0.38)
    r = int(min(gw, gh) * 0.55)
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    glow = glow.resize((width, height), Image.BILINEAR).filter(
        ImageFilter.GaussianBlur(radius=max(8, width // 24))
    )
    glow = glow.point(lambda a: int(a * 0.40))  # cap intensity so text stays legible
    accent_layer = Image.new("RGB", (width, height), accent)
    img = Image.composite(accent_layer, img, glow)

    draw = ImageDraw.Draw(img)

    # 3. Brain Pulse — 4 amber dots orbiting a centre, top-third of the canvas.
    bp_cx, bp_cy = width // 2, int(height * 0.26)
    orbit = max(10, int(height * 0.035))
    dot = max(3, int(height * 0.011))
    for ox, oy in ((0, -orbit), (orbit, 0), (0, orbit), (-orbit, 0)):
        draw.ellipse(
            [bp_cx + ox - dot, bp_cy + oy - dot, bp_cx + ox + dot, bp_cy + oy + dot],
            fill=_BRAND_AMBER,
        )

    # 4. Kicker (letter-spaced uppercase) centred under the Brain Pulse.
    if kicker:
        kfont = _load_font(max(12, int(height * 0.026)), bold=True)
        text = kicker.upper()
        spacing = max(2, int(height * 0.006))
        widths = [draw.textlength(ch, font=kfont) for ch in text]
        total = sum(widths) + spacing * (len(text) - 1)
        kx = (width - total) / 2
        ky = bp_cy + orbit + int(height * 0.03)
        for ch, w in zip(text, widths):
            draw.text((kx, ky), ch, font=kfont, fill=_BRAND_AMBER)
            kx += w + spacing

    # 5. Title — wrapped to ~80% width, max 4 lines, centred vertically.
    title_font = _load_font(int(height * 0.072), bold=True)
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

    line_h = int(height * 0.095)
    block_top = (height - line_h * len(lines)) // 2 + int(height * 0.04)
    y = block_top
    for line in lines:
        w_line = draw.textlength(line, font=title_font)
        draw.text(((width - w_line) / 2, y), line, font=title_font, fill=(232, 232, 244))
        y += line_h

    # 6. Subtitle (e.g. creator / mood), amber, below the title.
    if subtitle:
        sub_font = _load_font(int(height * 0.034), bold=False)
        w_sub = draw.textlength(subtitle, font=sub_font)
        draw.text(((width - w_sub) / 2, y + int(height * 0.01)), subtitle,
                  font=sub_font, fill=_BRAND_AMBER)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _generate_remote(prompt: str, width: int, height: int, negative_text: str) -> bytes:
    """Invoke the configured remote image backend. Raises on any failure."""
    settings = get_settings()
    if (settings.image_backend or "fal").lower() == "fal":
        from private_internet.content.fal_image import generate_image
        return await generate_image(prompt, width, height, negative_text=negative_text)
    # Bedrock (Nova Canvas) fallback path, honoured if image_backend == "bedrock".
    from private_internet.content.image_generator import PostImageGenerator
    return await PostImageGenerator()._invoke_nova_canvas(
        prompt, width=width, height=height, negative_text=negative_text
    )


async def generate_cover(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    *,
    fallback_title: str,
    kicker: str = "",
    fallback_subtitle: str = "",
    seed: str = "",
    negative_text: str = _DEFAULT_NEGATIVE,
) -> bytes:
    """Generate a cover, ALWAYS returning bytes.

    Tries the configured remote backend (fal.ai FLUX by default); on ANY failure
    — including an unfunded fal balance — renders the designed local fallback so
    the caller never has to handle a missing image. Never raises.
    """
    try:
        return await _generate_remote(prompt, width, height, negative_text)
    except Exception as exc:
        logger.warning(
            "Remote cover generation failed (%s); rendering designed local fallback.",
            exc,
        )
        return render_cover(
            width, height,
            title=fallback_title,
            kicker=kicker,
            subtitle=fallback_subtitle,
            seed=seed or fallback_title,
        )
