<script setup lang="ts">
/**
 * IntroVideo — the localized onboarding/intro film.
 *
 * Picks the language version from the active i18n locale and re-resolves
 * reactively when the user switches language (Settings). Before any choice
 * (onboarding) the locale follows the browser language. Unsupported locales
 * fall back to English. Until VITE_INTRO_VIDEO_BASE is configured, a calm
 * placeholder is shown instead of a broken <video>.
 */
import { computed } from 'vue'
import { useI18n } from '../i18n'
import { introVideoUrl, introVideoLang } from '../config/introVideo'
import BrainPulse from './ui/BrainPulse.vue'

withDefaults(
  defineProps<{
    autoplay?: boolean
    controls?: boolean
    muted?: boolean
    loop?: boolean
    poster?: string
  }>(),
  { autoplay: false, controls: true, muted: false, loop: false, poster: '' },
)

const { locale } = useI18n()
const lang = computed(() => introVideoLang(locale.value))
const src = computed(() => introVideoUrl(locale.value))
</script>

<template>
  <!-- :key forces the <video> element to reload its source when the language changes. -->
  <video
    v-if="src"
    :key="lang"
    class="intro-video"
    :src="src"
    :poster="poster || undefined"
    :controls="controls"
    :autoplay="autoplay"
    :muted="muted"
    :loop="loop"
    playsinline
  />
  <div v-else class="intro-video intro-video--placeholder" role="img" aria-label="Intro video coming soon">
    <BrainPulse :size="48" :slow="true" aria-hidden="true" />
    <span class="intro-video__label t-secondary">Intro video coming soon</span>
  </div>
</template>

<style scoped>
.intro-video {
  width: 100%;
  height: auto;
  display: block;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-lg, 12px);
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  background: #0c0c14; /* brief's deep indigo-black */
  object-fit: cover;
}
.intro-video--placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3, 12px);
  object-fit: unset;
}
.intro-video__label {
  font-size: var(--text-sm, 0.875rem);
}
</style>
