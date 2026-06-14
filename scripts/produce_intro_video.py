#!/usr/bin/env python3
"""Produce the Private Internet onboarding/intro video in every supported language.

Drives the repo's existing content machinery — no new generation tech:

  1. fal.ai Kling clips      content/fal_video.generate_video_clip()   (12 clips, once)
  2. ARIA background music   content/aria/music_client.generate_music() (1 track, once)
  3. ElevenLabs narration    content/elevenlabs_engine.ElevenLabsEngine (12 lines x lang)
  4. FFmpeg assembly + mux   content/ffmpeg_assembler.VideoAssembler + a final amix

Output: out/private_internet_intro_{en,de,fr,ru,ar}.mp4

Identical visuals across languages; only the narration changes. Visuals (clips) and
the music track are generated ONCE and reused for every language.

Everything is idempotent: any artifact already on disk is reused, so a re-run after a
failure (or to add a language) does not re-spend on clips/music it already made. Use
--force to regenerate.

Requirements at runtime (env / config.py — typically present on EC2, not local):
  FAL_AI_API_KEY        for the video clips
  ELEVENLABS_API_KEY    for narration + ARIA music
  ffmpeg + ffprobe      on PATH

Usage:
  python scripts/produce_intro_video.py                  # all 5 languages
  python scripts/produce_intro_video.py --langs en,de    # subset
  python scripts/produce_intro_video.py --scenes-only    # just generate the 12 clips
  python scripts/produce_intro_video.py --skip-music      # narration only, no bg music
  python scripts/produce_intro_video.py --force           # regenerate everything
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Make `private_internet` importable when run from a source checkout (no-op once installed).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from private_internet.content import fal_video, voice_config              # noqa: E402
from private_internet.content.aria import music_client                    # noqa: E402
from private_internet.content.elevenlabs_engine import ElevenLabsEngine   # noqa: E402
from private_internet.content.ffmpeg_assembler import (                   # noqa: E402
    VideoAssembler,
    VideoAssemblyError,
    _run_ffmpeg,
)
from private_internet.content.video_generator import ScriptSection        # noqa: E402

# ── Scene visual prompts (language-independent; from the production brief) ──────────
# One clip per scene. fal Kling makes a ~5s silent clip; the assembler loops it under
# each scene's narration, so the scene's on-screen length follows its narration length.
SCENE_PROMPTS: list[str] = [
    # 01 — The Problem
    "Cinematic close-up of a person's hands typing on a laptop at night. The screen "
    "reflects in their glasses. Warm amber desk lamp light. Dark indigo background. "
    "Shallow depth of field. The person pauses, looks uncertain, then closes the laptop "
    "lid slowly. Slow push-in camera move. Photorealistic, 35mm film aesthetic. "
    "No text, no logos. Intimate, thoughtful mood.",
    # 02 — The Question
    "Medium close-up of a person sitting at a desk at night, looking out a rain-streaked "
    "window. City lights blurred in the background, amber and indigo tones. They hold a "
    "warm coffee cup in both hands. Thoughtful, searching expression. Slow static shot. "
    "35mm film grain. No dialogue. Cinematic and intimate.",
    # 03 — Introducing Private Internet
    "A smartphone screen in someone's hand showing a dark, elegant app interface glowing "
    "softly with deep indigo tones and a warm amber accent. The thumb slowly scrolls. "
    "Camera pulls back slightly to reveal the person in a quiet, warmly lit room. "
    "Photorealistic, premium product feel. No visible text on screen. Calm, confident mood.",
    # 04 — The Brain
    "Close-up of a person writing in a notebook by candlelight, pen moving slowly across "
    "the page, the writing blurred and unreadable — only motion and intent. A laptop with "
    "a dark elegant interface is open nearby. Warm amber light, shallow depth of field. "
    "Camera slowly pushes in on the writing hand. Personal, private, intimate. 35mm aesthetic.",
    # 05 — PULSE
    "Person relaxing on a sofa, legs tucked underneath, reading a dark elegant news feed "
    "on a phone. They smile slightly at something they read. Warm lamp light. Slow zoom out "
    "revealing a cozy, quiet apartment at night. No text visible on screen. Calm, satisfied "
    "expression. Photorealistic. Intimate evening atmosphere.",
    # 06 — SIGNAL & STORIES
    "Close-up of a laptop screen showing a dark video player, a short film playing. The "
    "screen light illuminates the viewer's face in a dark room; their expression is engaged, "
    "absorbed. Warm amber reflections. Camera slowly circles to show the screen from the "
    "side. Cinematic. No text visible. Premium, intimate atmosphere.",
    # 07 — ARIA
    "Person wearing over-ear headphones, eyes closed, head slightly tilted back, expression "
    "of deep calm and absorption. Warm amber light from a window. Dark, blurred apartment "
    "background, early morning light. Slow push-in on the face. The headphone cable swings "
    "very slightly. Photorealistic, intimate and musical. 35mm film grain.",
    # 08 — Health & Wearables
    "Close-up of a person's wrist with a smartwatch, walking through an early morning city "
    "street, the screen showing abstract health data. Golden hour light. Steam from a coffee "
    "cup in the other hand. Slow-motion walk, camera at a low angle looking up slightly. "
    "Confident, healthy morning energy. Photorealistic. No readable text on the watch.",
    # 09 — Finances
    "Person at a clean desk in morning light through large windows, reviewing something on a "
    "laptop, a coffee cup nearby. Expression of calm clarity — not stress, not excitement, "
    "just understanding. Camera slowly pushes in on the face. Warm natural light. Dark laptop "
    "screen glowing with a minimal dark interface. No text visible. Confident, grounded mood.",
    # 10 — Privacy & Ownership
    "Extreme close-up of a hand holding a small physical key, turning it in a lock. Shallow "
    "depth of field, background blurred into warm amber bokeh. The key catches the light. "
    "Slow motion. The hand opens a door slightly — warm light spills through. Metaphorical, "
    "minimal, elegant, symbolic. Cinematic. No people visible beyond the hand.",
    # 11 — The Future
    "Wide shot of a person standing at a large window at night, looking out at a city skyline "
    "— small against the vast view but grounded and calm. They hold a phone loosely at their "
    "side. City lights in indigo and amber tones. Long slow push-in from behind. "
    "Contemplative, forward-looking. No dialogue. Cinematic scope. 35mm film aesthetic.",
    # 12 — Call to Action / End
    "Return to the opening shot: hands on a laptop at night, but this time the person opens "
    "the laptop with quiet confidence. The screen illuminates their face with warm, calm "
    "light. They begin to type. The camera holds steady — a sense of beginning. Warm amber "
    "glow, shallow depth of field. End on a still hold. Photorealistic, intimate, resolved.",
]

# ── Narration per language (from the production brief), one entry per scene ─────────
NARRATION: dict[str, list[str]] = {
    "en": [
        "Every day you hand your thoughts, your habits, your data to systems that use them against you.",
        "What if there was a different way?",
        "Private Internet is a personal AI platform that lives on your own server. Nothing leaves. Nothing is sold.",
        "At its core is the Brain — a private knowledge base that grows with everything you choose to share. The more you write, the smarter it gets.",
        "PULSE reads your brain and curates a personalised content feed — articles, analysis, and perspectives built specifically for how you think.",
        "SIGNAL generates short videos from your interests. STORIES creates films and series from the topics that matter to you.",
        "ARIA composes original music from your memories and moods — a personal soundtrack that no one else has.",
        "Your health data syncs live from your wearable devices, giving you plain-language insights that you actually understand.",
        "Your finances become clear — not charts and numbers, but honest analysis in plain language.",
        "Everything stays on your server. You can delete anything, at any time. You are the only one who can see it.",
        "We are building toward a world where your AI knows you completely because you chose to tell it — not because it was taken.",
        "Private Internet. Your AI. Your server. Your rules.",
    ],
    "de": [
        "Jeden Tag gibst du deine Gedanken, deine Gewohnheiten, deine Daten an Systeme weiter, die sie gegen dich einsetzen.",
        "Was wäre, wenn es einen anderen Weg gäbe?",
        "Private Internet ist eine persönliche KI-Plattform, die auf deinem eigenen Server läuft. Nichts verlässt ihn. Nichts wird verkauft.",
        "Im Kern steht das Gehirn — eine private Wissensdatenbank, die mit allem wächst, was du teilen möchtest. Je mehr du schreibst, desto intelligenter wird es.",
        "PULSE liest dein Gehirn und kuratiert einen personalisierten Content-Feed — Artikel, Analysen und Perspektiven, die genau zu deiner Denkweise passen.",
        "SIGNAL generiert kurze Videos aus deinen Interessen. STORIES erschafft Filme und Serien aus den Themen, die dir wichtig sind.",
        "ARIA komponiert originale Musik aus deinen Erinnerungen und Stimmungen — ein persönlicher Soundtrack, den sonst niemand hat.",
        "Deine Gesundheitsdaten werden live von deinen Wearables synchronisiert und geben dir verständliche Einblicke, die du wirklich nachvollziehen kannst.",
        "Deine Finanzen werden klar — keine Diagramme und Zahlen, sondern ehrliche Analysen in einfacher Sprache.",
        "Alles bleibt auf deinem Server. Du kannst alles jederzeit löschen. Nur du hast Zugriff darauf.",
        "Wir bauen auf eine Welt hin, in der deine KI dich vollständig kennt, weil du es ihr gesagt hast — nicht weil es gestohlen wurde.",
        "Private Internet. Deine KI. Dein Server. Deine Regeln.",
    ],
    "fr": [
        "Chaque jour, vous confiez vos pensées, vos habitudes, vos données à des systèmes qui les retournent contre vous.",
        "Et s'il existait une autre façon de faire ?",
        "Private Internet est une plateforme d'IA personnelle qui vit sur votre propre serveur. Rien ne quitte. Rien n'est vendu.",
        "Au cœur se trouve le Cerveau — une base de connaissances privée qui grandit avec tout ce que vous choisissez de partager. Plus vous écrivez, plus il devient intelligent.",
        "PULSE lit votre cerveau et compose un flux de contenu personnalisé — articles, analyses et perspectives construits spécifiquement pour votre façon de penser.",
        "SIGNAL génère de courtes vidéos à partir de vos intérêts. STORIES crée des films et des séries à partir des sujets qui vous importent.",
        "ARIA compose de la musique originale à partir de vos souvenirs et de vos humeurs — une bande-son personnelle que personne d'autre ne possède.",
        "Vos données de santé se synchronisent en temps réel depuis vos appareils connectés, vous offrant des analyses claires que vous comprenez vraiment.",
        "Vos finances deviennent lisibles — pas des graphiques et des chiffres, mais une analyse honnête en langage simple.",
        "Tout reste sur votre serveur. Vous pouvez tout supprimer, à tout moment. Vous êtes le seul à pouvoir y accéder.",
        "Nous construisons vers un monde où votre IA vous connaît complètement parce que vous avez choisi de lui confier — et non parce que cela a été pris.",
        "Private Internet. Votre IA. Votre serveur. Vos règles.",
    ],
    "ru": [
        "Каждый день вы отдаёте свои мысли, свои привычки, свои данные системам, которые используют их против вас.",
        "А что если существует другой путь?",
        "Private Internet — это персональная ИИ-платформа, которая работает на вашем собственном сервере. Ничто не покидает его. Ничто не продаётся.",
        "В основе лежит Мозг — частная база знаний, которая растёт вместе со всем, чем вы решаете поделиться. Чем больше вы пишете, тем умнее он становится.",
        "PULSE читает ваш мозг и формирует персонализированную ленту контента — статьи, аналитику и точки зрения, созданные специально под ваш образ мышления.",
        "SIGNAL создаёт короткие видео из ваших интересов. STORIES генерирует фильмы и сериалы на темы, которые важны именно вам.",
        "ARIA сочиняет оригинальную музыку из ваших воспоминаний и настроений — личный саундтрек, которого нет больше ни у кого.",
        "Ваши данные о здоровье синхронизируются в реальном времени с носимых устройств, давая вам понятные выводы, которые вы действительно можете осмыслить.",
        "Ваши финансы становятся прозрачными — не графики и цифры, а честный анализ на простом языке.",
        "Всё остаётся на вашем сервере. Вы можете удалить что угодно в любой момент. Только вы можете это видеть.",
        "Мы строим мир, в котором ваш ИИ знает вас полностью, потому что вы сами решили ему рассказать — а не потому что это было взято без спроса.",
        "Private Internet. Ваш ИИ. Ваш сервер. Ваши правила.",
    ],
    "ar": [
        "كل يوم، تُسلّم أفكارَك وعاداتِك وبياناتِك لأنظمة تستخدمها ضدَّك.",
        "ماذا لو كان ثمّة طريقٌ آخر؟",
        "Private Internet منصةُ ذكاء اصطناعي شخصية تعيش على خادمك الخاص. لا شيء يغادره. لا شيء يُباع.",
        "في جوهرها يقع الدماغ — قاعدة معرفة خاصة تنمو بكل ما تختار مشاركته. كلما كتبتَ أكثر، ازداد ذكاءً.",
        "يقرأ PULSE دماغَك ويُنسّق تغذيةَ محتوى مُخصَّصة لك — مقالات وتحليلات ووجهات نظر مبنية خصيصاً لطريقة تفكيرك.",
        "يُولِّد SIGNAL مقاطع فيديو قصيرة من اهتماماتك. ويصنع STORIES أفلاماً ومسلسلات من الموضوعات التي تعنيك.",
        "يؤلِّف ARIA موسيقى أصيلة من ذكرياتك وأمزجتك — موسيقى تخصُّك وحدَك، لا يملكها سواك.",
        "تتزامن بياناتك الصحية لحظةً بلحظة من أجهزتك القابلة للارتداء، لتمنحك تحليلات واضحة تفهمها فعلاً.",
        "تصبح أموالك واضحة — لا رسوماً بيانية وأرقاماً جافة، بل تحليلٌ صادق بلغة بسيطة.",
        "كل شيء يبقى على خادمك. يمكنك حذف أي شيء في أي وقت. أنتَ وحدَك من يملك الوصول إليه.",
        "نحن نبني نحو عالَمٍ يعرف فيه ذكاؤك الاصطناعي كلَّ شيء عنك لأنك اخترتَ أن تُخبره — لا لأن ذلك أُخِذ منك.",
        "Private Internet. ذكاؤك الاصطناعي. خادمُك. قواعدُك.",
    ],
}

# Background music prompt for ARIA (calm, focused, sits under the narration).
MUSIC_PROMPT = (
    "Calm, focused ambient cinematic underscore. Warm, intimate, minimal. Soft sustained "
    "synth pads, gentle felt piano, subtle low warmth. No drums, no melody hooks, no "
    "vocals. Slow and contemplative — a thoughtful short film about personal sovereignty "
    "over data. Suitable as quiet background under spoken narration."
)
MUSIC_VOLUME = 0.15  # ARIA track level under the narration (brief: ~-20 dB / 'just perceptible')

SUPPORTED_LANGS = ["en", "de", "fr", "ru", "ar"]


def _log(msg: str) -> None:
    print(msg, flush=True)


def generate_scenes(scenes_dir: Path, force: bool) -> list[Path]:
    """Generate the 12 fal.ai clips once. Cached on disk; returns the 12 clip paths."""
    scenes_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, prompt in enumerate(SCENE_PROMPTS, start=1):
        clip = scenes_dir / f"scene_{i:02d}.mp4"
        if clip.exists() and not force:
            _log(f"  scene {i:02d}: cached ({clip.name})")
        else:
            _log(f"  scene {i:02d}: generating via fal.ai Kling…")
            data = asyncio.run(
                fal_video.generate_video_clip(prompt, duration="5", aspect_ratio="16:9")
            )
            clip.write_bytes(data)
            _log(f"  scene {i:02d}: wrote {len(data):,} bytes")
        paths.append(clip)
    return paths


def generate_music(out_dir: Path, force: bool) -> Path | None:
    """Generate the ARIA background track once. Returns its path (or None on stub/failure)."""
    track = out_dir / "aria_background.mp3"
    if track.exists() and not force:
        _log(f"  music: cached ({track.name})")
        return track
    _log("  music: generating ARIA background track…")
    try:
        data = music_client.generate_music(MUSIC_PROMPT, duration_seconds=30)
    except Exception as exc:  # network etc. — proceed without music rather than abort
        _log(f"  music: FAILED ({exc}); videos will have narration only")
        return None
    track.write_bytes(data)
    _log(f"  music: wrote {len(data):,} bytes")
    return track


def generate_narration(lang: str, narr_dir: Path, engine: ElevenLabsEngine, force: bool) -> list[Path]:
    """Generate the 12 per-scene narration mp3s for one language. Cached on disk."""
    narr_dir.mkdir(parents=True, exist_ok=True)
    voice_id = voice_config.get_voice_id(lang)
    lines = NARRATION[lang]
    paths: list[Path] = []
    for i, text in enumerate(lines, start=1):
        mp3 = narr_dir / f"narration_{lang}_{i:02d}.mp3"
        if mp3.exists() and not force:
            _log(f"    {lang} narration {i:02d}: cached")
        else:
            _log(f"    {lang} narration {i:02d}: synthesizing…")
            engine.synthesize_section(text, voice_id, lang, str(mp3))
        paths.append(mp3)
    return paths


def mux_music(assembled: Path, music: Path, out: Path) -> None:
    """Mix the ARIA track (looped, low volume) under the already-narrated video."""
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", str(assembled),
        "-stream_loop", "-1", "-i", str(music),
        "-filter_complex",
        f"[1:a]volume={MUSIC_VOLUME}[bg];"
        f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        str(out),
    ])


def build_language(
    lang: str,
    scene_clips: list[Path],
    music: Path | None,
    out_dir: Path,
    work_dir: Path,
    force: bool,
) -> Path:
    """Assemble visuals + this language's narration, then mux ARIA music. Returns final mp4."""
    final = out_dir / f"private_internet_intro_{lang}.mp4"
    if final.exists() and not force:
        _log(f"  {lang}: cached final ({final.name})")
        return final

    engine = ElevenLabsEngine()
    narr_paths = generate_narration(lang, work_dir / "narration", engine, force)

    sections = [
        ScriptSection(id=f"scene_{i:02d}", text=NARRATION[lang][i - 1], image_prompt=SCENE_PROMPTS[i - 1])
        for i in range(1, len(SCENE_PROMPTS) + 1)
    ]

    # Assemble visuals + per-scene narration (no bg music yet).
    narrated = work_dir / f"narrated_{lang}.mp4"
    _log(f"  {lang}: assembling visuals + narration…")
    VideoAssembler().assemble(
        sections=sections,
        image_paths=[str(p) for p in scene_clips],
        audio_paths=[str(p) for p in narr_paths],
        output_path=str(narrated),
    )

    if music is not None:
        _log(f"  {lang}: mixing ARIA background music…")
        mux_music(narrated, music, final)
        narrated.unlink(missing_ok=True)
    else:
        narrated.replace(final)
    _log(f"  {lang}: done -> {final}")
    return final


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--langs", default=",".join(SUPPORTED_LANGS),
                    help="comma-separated subset of: " + ",".join(SUPPORTED_LANGS))
    ap.add_argument("--out", default="out", help="output directory (default: out/)")
    ap.add_argument("--work", default="out/work", help="intermediate artifacts dir")
    ap.add_argument("--scenes-only", action="store_true", help="only generate the 12 clips, then stop")
    ap.add_argument("--skip-music", action="store_true", help="do not generate/mix ARIA background music")
    ap.add_argument("--force", action="store_true", help="regenerate everything, ignoring cached files")
    args = ap.parse_args()

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    bad = [l for l in langs if l not in SUPPORTED_LANGS]
    if bad:
        _log(f"ERROR: unsupported language(s): {bad}. Supported: {SUPPORTED_LANGS}")
        return 2

    out_dir = Path(args.out)
    work_dir = Path(args.work)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Fail fast with a clear message if ffmpeg isn't available.
    if not _ffmpeg_available():
        _log("ERROR: ffmpeg/ffprobe not found on PATH (apt install ffmpeg).")
        return 3

    _log("== Phase 1: video clips (language-independent) ==")
    scene_clips = generate_scenes(work_dir / "scenes", args.force)
    if args.scenes_only:
        _log("scenes-only: stopping after clip generation.")
        return 0

    music: Path | None = None
    if not args.skip_music:
        _log("== Phase 2: ARIA background music (once) ==")
        music = generate_music(work_dir, args.force)

    _log("== Phase 3: per-language narration + assembly ==")
    finals: list[Path] = []
    failures: list[str] = []
    for lang in langs:
        try:
            finals.append(build_language(lang, scene_clips, music, out_dir, work_dir, args.force))
        except (VideoAssemblyError, RuntimeError, OSError) as exc:
            _log(f"  {lang}: FAILED — {exc}")
            failures.append(lang)

    _log("\n== Summary ==")
    for f in finals:
        _log(f"  OK  {f}")
    for lang in failures:
        _log(f"  FAIL {lang}")
    return 1 if failures else 0


def _ffmpeg_available() -> bool:
    for tool in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([tool, "-version"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
