/**
 * Localized onboarding / intro video resolution.
 *
 * The intro video is produced in 5 languages (see scripts/produce_intro_video.py).
 * The UI picks the version matching the active locale; locales we have NOT produced
 * a video for (es, zh, sv, tlh, …) fall back to English.
 *
 * The video URL is derived from the active i18n `locale`, so:
 *   - On the onboarding page (before the user has chosen a language) it follows the
 *     browser language, because i18n's detect() seeds `locale` from navigator.language.
 *   - When the user changes the language in Settings, setLocale() updates `locale`
 *     reactively and any computed using introVideoUrl(locale.value) re-resolves.
 *
 * The 5 mp4s are served from the content CloudFront distribution under /intro/.
 * Self-hosters on a different distribution can override the base at build time with
 * VITE_INTRO_VIDEO_BASE (e.g. "https://dxxxx.cloudfront.net/intro").
 * Files are named: private_internet_intro_{en,de,fr,ru,ar}.mp4
 * If the base is ever empty, introVideoUrl() returns '' and <IntroVideo> shows a placeholder.
 */

// Languages we have an intro video for.
export const INTRO_VIDEO_LANGS = ['en', 'de', 'fr', 'ru', 'ar'] as const
export type IntroVideoLang = (typeof INTRO_VIDEO_LANGS)[number]

// Default: the content CloudFront distribution, /intro prefix. Override via env for self-hosting.
const DEFAULT_INTRO_VIDEO_BASE = 'https://d20aaqlrgvxz3g.cloudfront.net/intro'

// Base URL of the uploaded videos (no trailing slash).
export const INTRO_VIDEO_BASE: string = (
  import.meta.env.VITE_INTRO_VIDEO_BASE || DEFAULT_INTRO_VIDEO_BASE
).replace(/\/$/, '')

/** Map any i18n locale to the closest produced video language (English fallback). */
export function introVideoLang(locale: string): IntroVideoLang {
  return (INTRO_VIDEO_LANGS as readonly string[]).includes(locale)
    ? (locale as IntroVideoLang)
    : 'en'
}

/** Full URL of the intro video for a locale, or '' if the base isn't configured yet. */
export function introVideoUrl(locale: string): string {
  if (!INTRO_VIDEO_BASE) return ''
  return `${INTRO_VIDEO_BASE}/private_internet_intro_${introVideoLang(locale)}.mp4`
}
