<script setup lang="ts">
/**
 * Global share button — drop into any section.
 *
 *   <ShareButton kind="aria_track" :ref-id="track.id" :text="track.title" />
 *   <ShareButton kind="health_card" :highlight="{ headline, caption }" label="Share snapshot" />
 *
 * On click it mints a public share link, then opens the OS share sheet on mobile
 * or a platform menu (X / WhatsApp / Threads / Telegram / Facebook / Reddit /
 * Bluesky / Email + copy link) on desktop. The menu is teleported to <body> with
 * fixed positioning so it is never clipped by a card's `overflow: hidden`.
 */
import { ref, nextTick, onBeforeUnmount } from 'vue'
import PIIcon from './PIIcon.vue'
import { useToast } from './useToast'
import {
  createShare, canNativeShare, nativeShare, shareTargets, copyLink,
  type ShareKind, type ShareHighlight, type ShareResult, type ShareTarget,
} from '../../composables/useShare'

/** Single-path brand glyphs (simple-icons style, drawn in white on a brand tile). */
const BRAND_PATHS: Record<string, string> = {
  x: 'M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z',
  whatsapp: 'M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893A11.821 11.821 0 0 0 20.465 3.488',
  threads: 'M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.03-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.74-1.752-2.964-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 0 1 3.02.142c-.126-.742-.375-1.332-.75-1.757-.513-.586-1.308-.883-2.359-.89h-.029c-.844 0-1.992.232-2.721 1.32l-1.696-1.142c.98-1.454 2.568-2.256 4.478-2.256h.044c3.194.02 5.097 1.975 5.287 5.388.108.046.216.094.321.142 1.49.7 2.58 1.761 3.154 3.07.797 1.82.871 4.79-1.548 7.158-1.85 1.81-4.094 2.628-7.277 2.65Z',
  telegram: 'M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z',
  facebook: 'M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0 .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628 3.874 10.35 9.101 11.647Z',
  reddit: 'M24 11.779c0-1.459-1.192-2.645-2.657-2.645-.715 0-1.363.286-1.84.746-1.81-1.191-4.259-1.949-6.971-2.046l1.483-4.669 4.016.941-.006.058c0 1.193.975 2.163 2.174 2.163 1.198 0 2.172-.97 2.172-2.163s-.975-2.164-2.172-2.164c-.92 0-1.704.574-2.021 1.379l-4.329-1.015c-.189-.046-.381.063-.44.249l-1.654 5.207c-2.838.034-5.409.798-7.3 2.025-.474-.438-1.103-.712-1.799-.712-1.465 0-2.656 1.187-2.656 2.646 0 1.063.629 1.974 1.531 2.392-.04.246-.06.496-.06.749 0 3.792 4.489 6.886 10.007 6.886 5.518 0 10.007-3.094 10.007-6.886 0-.249-.02-.496-.059-.74.917-.414 1.555-1.327 1.555-2.401zM7.054 13.466c0-.835.679-1.515 1.515-1.515.835 0 1.514.68 1.514 1.515s-.679 1.515-1.514 1.515c-.836 0-1.515-.68-1.515-1.515zm8.611 4.658c-.708.706-1.952 1.024-3.659 1.024l-.012-.002-.012.002c-1.707 0-2.951-.318-3.659-1.024a.366.366 0 0 1 0-.516.366.366 0 0 1 .516 0c.541.541 1.587.783 3.143.783l.012.002.012-.002c1.555 0 2.601-.242 3.143-.783a.366.366 0 0 1 .516 0 .364.364 0 0 1-.001.516zm-.27-3.143c-.835 0-1.514-.68-1.514-1.515s.679-1.515 1.514-1.515c.836 0 1.515.68 1.515 1.515s-.679 1.515-1.515 1.515z',
  bluesky: 'M12 10.8c-1.087-2.114-4.046-6.053-6.798-7.995C2.566.944 1.561 1.266.902 1.565.139 1.908 0 3.08 0 3.768c0 .69.378 5.65.624 6.479.815 2.736 3.713 3.66 6.383 3.364.136-.02.275-.039.415-.056-.138.022-.276.04-.415.056-3.912.58-7.387 2.005-2.83 7.078 5.013 5.19 6.87-1.113 7.823-4.308.953 3.195 2.05 9.271 7.733 4.308 4.267-4.308 1.172-6.498-2.74-7.078a8.741 8.741 0 0 1-.415-.056c.14.017.279.036.415.056 2.67.297 5.568-.628 6.383-3.364.246-.828.624-5.79.624-6.479 0-.688-.139-1.86-.902-2.203-.659-.299-1.664-.621-4.3 1.24C16.046 4.748 13.087 8.687 12 10.8Z',
  email: 'M3 5h18a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zm9 7.5L20 7H4l8 5.5zM4 8.2V18h16V8.2l-8 5.5-8-5.5z',
  instagram: 'M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881z',
  youtube: 'M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z',
  signal: 'M12 2C6.477 2 2 5.94 2 10.8c0 2.39 1.08 4.55 2.84 6.12L4 22l5.3-1.5c.85.2 1.76.3 2.7.3 5.523 0 10-3.94 10-8.8S17.523 2 12 2z',
}

const props = withDefaults(defineProps<{
  kind: ShareKind
  refId?: string
  highlight?: ShareHighlight
  text?: string
  label?: string
  /** 'ghost' = subtle text+icon, 'icon' = round icon-only, 'button' = filled. */
  variant?: 'ghost' | 'icon' | 'button'
}>(), { label: 'Share', variant: 'ghost' })

const toast = useToast()
const open = ref(false)
const loading = ref(false)
const targets = ref<ShareTarget[]>([])
const pos = ref({ top: 0, left: 0 })
const rootEl = ref<HTMLElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)
let result: ShareResult | null = null

const MENU_WIDTH = 224

async function ensureShare(): Promise<ShareResult | null> {
  if (result) return result
  loading.value = true
  try {
    result = await createShare({
      kind: props.kind, refId: props.refId, highlight: props.highlight, text: props.text,
    })
    return result
  } catch {
    toast('Could not create share link', 'error')
    return null
  } finally {
    loading.value = false
  }
}

function placeMenu() {
  const trigger = rootEl.value?.querySelector('.share-trigger') as HTMLElement | null
  if (!trigger) return
  const r = trigger.getBoundingClientRect()
  const left = Math.max(8, Math.min(r.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8))
  // Open upwards when there isn't room below.
  const below = window.innerHeight - r.bottom
  const top = below < 380 && r.top > below ? Math.max(8, r.top - 360) : r.bottom + 6
  pos.value = { top, left }
}

async function onTrigger() {
  if (open.value) { close(); return }
  const r = await ensureShare()
  if (!r) return
  // Mobile: try the native sheet first; fall back to our menu if cancelled.
  if (canNativeShare()) {
    const done = await nativeShare(r)
    if (done) return
  }
  targets.value = shareTargets(r)
  placeMenu()
  open.value = true
  await nextTick()
  window.addEventListener('click', onOutside, true)
  window.addEventListener('keydown', onKey)
  window.addEventListener('resize', close)
  window.addEventListener('scroll', close, true)
}

function close() {
  open.value = false
  window.removeEventListener('click', onOutside, true)
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', close)
  window.removeEventListener('scroll', close, true)
}

function onOutside(e: MouseEvent) {
  const t = e.target as Node
  if (rootEl.value?.contains(t) || menuEl.value?.contains(t)) return
  close()
}
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }

async function pick(t: ShareTarget) {
  if (!result) return
  if (t.copyOnly || !t.href) {
    const ok = await copyLink(result)
    toast(ok ? `Link copied — paste it in ${t.label}` : 'Copy failed', ok ? 'success' : 'error')
  } else {
    window.open(t.href, '_blank', 'noopener,noreferrer,width=600,height=560')
  }
  close()
}

async function onCopy() {
  if (!result) return
  const ok = await copyLink(result)
  toast(ok ? 'Link copied' : 'Copy failed', ok ? 'success' : 'error')
  close()
}

onBeforeUnmount(close)
</script>

<template>
  <div ref="rootEl" class="share-root">
    <button
      class="share-trigger"
      :class="`share-trigger--${variant}`"
      :disabled="loading"
      :aria-label="label"
      :title="label"
      @click.stop="onTrigger"
    >
      <PIIcon name="share" :size="variant === 'icon' ? 18 : 16" />
      <span v-if="variant !== 'icon'" class="share-trigger__label">
        {{ loading ? 'Sharing…' : label }}
      </span>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="menuEl"
        class="share-menu"
        role="menu"
        :style="{ top: pos.top + 'px', left: pos.left + 'px', width: MENU_WIDTH + 'px' }"
      >
        <button class="share-item share-item--copy" @click.stop="onCopy">
          <span class="share-tile share-tile--neutral"><PIIcon name="link" :size="15" /></span>
          <span>Copy link</span>
        </button>
        <div class="share-divider" />
        <button
          v-for="t in targets"
          :key="t.id"
          class="share-item"
          role="menuitem"
          @click.stop="pick(t)"
        >
          <span class="share-tile" :style="{ background: t.color }">
            <svg viewBox="0 0 24 24" fill="#fff" width="15" height="15" aria-hidden="true">
              <path :d="BRAND_PATHS[t.id]" />
            </svg>
          </span>
          <span>{{ t.label }}</span>
          <span v-if="t.copyOnly" class="share-hint">copy</span>
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.share-root { position: relative; display: inline-flex; }

.share-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  color: var(--text-secondary); background: transparent;
  border: 1px solid transparent; border-radius: var(--radius-sm, 8px);
  padding: 6px 10px; transition: background .15s, color .15s, border-color .15s;
}
.share-trigger:hover:not(:disabled) { color: var(--text-primary); background: var(--background-elevated, rgba(255,255,255,.05)); }
.share-trigger:disabled { opacity: .6; cursor: default; }
.share-trigger--icon { padding: 7px; border-radius: 999px; }
.share-trigger--button {
  color: #fff; background: var(--accent-primary, #6b5cff);
  border-color: var(--accent-primary, #6b5cff); padding: 8px 14px;
}
.share-trigger--button:hover:not(:disabled) { filter: brightness(1.06); color: #fff; }

.share-menu {
  position: fixed; z-index: 1000;
  padding: 6px; max-height: 360px; overflow-y: auto;
  background: var(--background-surface, #14141f);
  border: 1px solid var(--border-subtle, #26263a);
  border-radius: var(--radius-md, 12px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, .45);
}
.share-item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  font: inherit; font-size: 13px; text-align: left; cursor: pointer;
  color: var(--text-primary); background: transparent; border: 0;
  padding: 7px 8px; border-radius: var(--radius-sm, 8px);
}
.share-item:hover { background: var(--background-elevated, rgba(255,255,255,.06)); }
.share-item--copy { font-weight: 600; }
.share-divider { height: 1px; margin: 5px 6px; background: var(--border-subtle, #26263a); }
.share-tile {
  display: grid; place-items: center; width: 26px; height: 26px; flex: none;
  border-radius: 7px; color: #fff;
}
.share-tile--neutral { background: var(--border-strong, #3a3a52); color: var(--text-primary); }
.share-hint {
  margin-left: auto; font-size: 10px; letter-spacing: .04em; text-transform: uppercase;
  color: var(--text-tertiary, #8a8aa0);
}
</style>
