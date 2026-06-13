<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { requireAuth } from '../composables/useAuth'
import { API_BASE } from '../config/env'
import BrandMark from '../components/ui/BrandMark.vue'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PiButton from '../components/ui/PiButton.vue'
import PiTextarea from '../components/ui/PiTextarea.vue'
import PiCard from '../components/ui/PiCard.vue'
import Pills from '../components/ui/Pills.vue'
import UploadZone from '../components/ui/UploadZone.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PIIcon from '../components/ui/PIIcon.vue'

// ── router ───────────────────────────────────────────────────────────────────
const router = useRouter()
const route  = useRoute()

// Banner shown when landing here from an email-verification redirect.
const emailVerifiedBanner = ref(false)

onMounted(() => {
  // If the backend redirected here with ?token=...&verified=1, store the JWT
  // so requireAuth() calls work immediately.
  const urlToken = route.query.token as string | undefined
  const verified = route.query.verified as string | undefined

  if (urlToken) {
    // Import storeJwt is not exported, but we can leverage the sessionStorage
    // key directly (same as storeJwt internals) to avoid circular imports.
    const expMs = (() => {
      try {
        const seg = urlToken.split('.')[1]
        if (!seg) return null
        const j = JSON.parse(atob(seg.replace(/-/g, '+').replace(/_/g, '/'))) as { exp?: number }
        return typeof j.exp === 'number' ? j.exp * 1000 : null
      } catch { return null }
    })() ?? (Date.now() + 7 * 24 * 60 * 60 * 1000)
    sessionStorage.setItem('pi_access_token', urlToken)
    sessionStorage.setItem('pi_token_expires_at', String(expMs))
    sessionStorage.removeItem('pi_refresh_token')
  }

  if (verified === '1') {
    emailVerifiedBanner.value = true
  }
})

// ── wizard state ─────────────────────────────────────────────────────────────
const TOTAL = 5
const step = ref(1)
const progressPct = computed(() => `${(step.value / TOTAL) * 100}%`)

// ── step 2 — introduction ────────────────────────────────────────────────────
const introText = ref('')
const introSaved = ref(false)
const introSavedHash = ref('')
let introTimer: ReturnType<typeof setTimeout> | null = null

function hashStr(s: string): string {
  // Simple hash to detect if content changed since last save
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0
  }
  return String(h)
}

watch(introText, (val) => {
  introSaved.value = false
  if (introTimer) clearTimeout(introTimer)
  if (!val.trim()) return
  introTimer = setTimeout(() => {
    saveIntro()
  }, 3000)
})

async function saveIntro(): Promise<void> {
  const text = introText.value.trim()
  if (!text) return
  const h = hashStr(text)
  if (h === introSavedHash.value) return // already saved this exact content
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/memory/text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ title: 'Introduction', content: text, tags: ['introduction', 'onboarding', 'profile'] }),
    })
    if (res.ok) {
      introSavedHash.value = h
      introSaved.value = true
    }
  } catch {
    // best-effort — silent fail
  }
}

onBeforeUnmount(() => {
  if (introTimer) clearTimeout(introTimer)
})

// ── step 3 — health devices ──────────────────────────────────────────────────
const HEALTH_TABS = ['Apple Watch', 'Samsung', 'Garmin', 'Smart Scale', 'Coming soon'] as const
type HealthTab = typeof HEALTH_TABS[number]

const healthTab = ref<HealthTab>('Apple Watch')

const ICON_FOR: Record<HealthTab, string> = {
  'Apple Watch': 'watch',
  'Samsung': 'watch',
  'Garmin': 'device',
  'Smart Scale': 'scale',
  'Coming soon': 'plus',
}

// Per-zone upload state for step 3
const healthUploadState = ref<'idle' | 'uploading' | 'success' | 'error'>('idle')

async function handleHealthFiles(files: File[]): Promise<void> {
  const file = files[0]
  if (!file) return
  healthUploadState.value = 'uploading'
  try {
    const token = await requireAuth()
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${API_BASE}/api/file`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
    healthUploadState.value = res.ok ? 'success' : 'error'
  } catch {
    healthUploadState.value = 'error'
  }
}

// Reset health upload state when tab changes
watch(healthTab, () => { healthUploadState.value = 'idle' })

// ── step 4 — documents ───────────────────────────────────────────────────────
interface DocZone {
  icon: string
  name: string
  desc: string
  fmt: string
  state: 'idle' | 'uploading' | 'success' | 'error'
}

const docZones = ref<DocZone[]>([
  { icon: 'finances', name: 'Financial documents', desc: 'Statements, invoices, anything money.', fmt: 'PDF, CSV, XLSX', state: 'idle' },
  { icon: 'file',     name: 'CV & career',         desc: 'Your CV, portfolio, references.',      fmt: 'PDF, DOCX',    state: 'idle' },
  { icon: 'health',   name: 'Medical records',      desc: 'Reports, results, prescriptions.',     fmt: 'PDF, images',  state: 'idle' },
])

async function handleDocFiles(idx: number, files: File[]): Promise<void> {
  const file = files[0]
  if (!file) return
  docZones.value[idx].state = 'uploading'
  try {
    const token = await requireAuth()
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${API_BASE}/api/file`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
    docZones.value[idx].state = res.ok ? 'success' : 'error'
  } catch {
    docZones.value[idx].state = 'error'
  }
}

// ── step 5 — complete ────────────────────────────────────────────────────────
const CHECK_ITEMS = [
  'Brain created',
  'Introduction saved',
  'Modules connected to your brain',
  'Privacy verified — data stays on your server',
]
const shownCount = ref(0)
let checkTimers: ReturnType<typeof setTimeout>[] = []

function runCheckAnimation(): void {
  checkTimers.forEach(clearTimeout)
  checkTimers = []
  shownCount.value = 0
  CHECK_ITEMS.forEach((_, i) => {
    checkTimers.push(setTimeout(() => { shownCount.value = Math.max(shownCount.value, i + 1) }, 200 * (i + 1)))
  })
}

// ── navigation ────────────────────────────────────────────────────────────────
async function patchOnboarding(patch: { onboarding_step?: number; onboarding_completed?: boolean }): Promise<void> {
  try {
    const token = await requireAuth()
    await fetch(`${API_BASE}/api/auth/onboarding`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(patch),
    })
  } catch {
    // best-effort
  }
}

async function advance(): Promise<void> {
  // Step 2: save intro if non-empty and unsaved
  if (step.value === 2) {
    if (introTimer) { clearTimeout(introTimer); introTimer = null }
    await saveIntro()
  }

  if (step.value < TOTAL) {
    const next = step.value + 1
    step.value = next
    patchOnboarding({ onboarding_step: next }) // fire-and-forget
    if (next === TOTAL) runCheckAnimation()
  } else {
    // Step 5 — finish
    await patchOnboarding({ onboarding_completed: true })
    router.replace('/overview')
  }
}

async function skip(): Promise<void> {
  if (step.value < TOTAL) {
    const next = step.value + 1
    step.value = next
    patchOnboarding({ onboarding_step: next })
    if (next === TOTAL) runCheckAnimation()
  }
}

const ctaLabel = computed(() => {
  if (step.value === 1) return 'Set up my brain'
  if (step.value === TOTAL) return 'Open my dashboard'
  return 'Continue'
})

const showSkip = computed(() => step.value > 1 && step.value < TOTAL)

onBeforeUnmount(() => {
  checkTimers.forEach(clearTimeout)
})
</script>

<template>
  <div class="pi-onb" :data-arrival="step === 1 ? 'true' : undefined">
    <!-- Top bar -->
    <div class="pi-onb__top">
      <div style="display: flex; align-items: center; gap: var(--space-2);">
        <BrandMark :size="20" />
        <span style="font-family: var(--font-display); font-weight: 600; font-size: var(--text-sm); white-space: nowrap;">
          Private Internet
        </span>
      </div>
      <span class="t-mono t-secondary" style="font-size: var(--text-sm);">Step {{ step }} of {{ TOTAL }}</span>
    </div>

    <!-- Progress track -->
    <div class="pi-onb__track">
      <div class="pi-onb__bar" :style="{ width: progressPct }" />
    </div>

    <!-- Email verified banner -->
    <div
      v-if="emailVerifiedBanner"
      role="status"
      style="
        background: var(--success-surface);
        color: var(--success);
        border-bottom: 1px solid var(--success);
        padding: var(--space-3) var(--space-6);
        font-size: var(--text-sm);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
      "
    >
      <span>Your email has been verified. Welcome to Private Internet.</span>
      <button
        type="button"
        style="background: none; border: none; color: var(--success); cursor: pointer; padding: 0; font-size: var(--text-xs); opacity: 0.7;"
        @click="emailVerifiedBanner = false"
        aria-label="Dismiss"
      >Dismiss</button>
    </div>

    <!-- Body -->
    <div class="pi-onb__body">
      <div class="pi-onb__inner" :key="step" style="animation: pi-fade-in .18s var(--ease);">

        <!-- Step 1: Welcome -->
        <template v-if="step === 1">
          <div style="display: flex; margin-bottom: var(--space-5);">
            <BrainPulse :size="56" :slow="true" aria-hidden="true" />
          </div>
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-4);">
            Your private internet starts here.
          </h1>
          <div
            class="t-serif"
            style="font-size: var(--text-md); line-height: 1.8; color: var(--text-secondary); display: flex; flex-direction: column; gap: var(--space-3);"
          >
            <p>
              At the center of Private Internet is your
              <strong style="color: var(--text-primary);">brain</strong>
              — a private knowledge base that grows as you add notes, upload documents, and connect devices.
            </p>
            <p>Every part of the platform reads from your brain and gets more personal over time. Nothing is sold. Nothing leaves your server.</p>
            <p>Let's set it up. It takes a few minutes, and you can change everything later.</p>
          </div>
        </template>

        <!-- Step 2: Introduction -->
        <template v-else-if="step === 2">
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-3);">Write your introduction</h1>
          <p class="t-secondary" style="font-size: var(--text-base); margin-bottom: var(--space-5); max-width: 560px;">
            Tell your brain who you are — your work, what you care about, what you're working through. This is the first thing it learns. Any language. No format.
          </p>
          <div style="position: relative;">
            <PiTextarea
              :serif="true"
              v-model="introText"
              placeholder="I'm a…"
              style="min-height: 200px; padding-bottom: 40px;"
            />
            <div style="position: absolute; right: 12px; bottom: 12px; display: flex; gap: var(--space-3); align-items: center;">
              <span
                v-if="introSaved"
                class="t-mono"
                style="font-size: var(--text-xs); color: var(--brain-amber);"
              >&#10003; Saved</span>
              <span class="pi-counter">{{ introText.length }} chars</span>
            </div>
          </div>
        </template>

        <!-- Step 3: Health devices -->
        <template v-else-if="step === 3">
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-3);">Connect health devices</h1>
          <p class="t-secondary" style="font-size: var(--text-base); margin-bottom: var(--space-5); max-width: 560px;">
            Optional. Upload an export from any device and its trends become part of your brain. There's no live account link — only files you choose to share.
          </p>
          <Pills
            :options="[...HEALTH_TABS]"
            :modelValue="healthTab"
            @update:modelValue="(v) => (healthTab = v as HealthTab)"
          />
          <PiCard style="margin-top: var(--space-5);">
            <EmptyState
              v-if="healthTab === 'Coming soon'"
              icon="plus"
              title="More devices soon"
              desc="We're adding Fitbit, Oura, and Withings next. Connected devices will appear here."
            />
            <div
              v-else
              style="display: flex; flex-direction: column; gap: var(--space-4);"
            >
              <div style="display: flex; align-items: center; gap: var(--space-3);">
                <span class="pi-device__ic">
                  <PIIcon :name="ICON_FOR[healthTab]" :size="20" />
                </span>
                <div style="font-family: var(--font-display); font-weight: 500;">{{ healthTab }}</div>
              </div>
              <ol
                class="t-secondary"
                style="font-size: var(--text-sm); padding-left: var(--space-4); line-height: 1.8; margin: 0;"
              >
                <li>Open the device's companion app</li>
                <li>Find Export or Download your data</li>
                <li>Upload the file below</li>
              </ol>
              <UploadZone
                :compact="true"
                :title="`Upload ${healthTab} export`"
                hint="Your file is processed on your server only"
                @files="handleHealthFiles"
              />
              <p
                v-if="healthUploadState === 'error'"
                style="font-size: var(--text-sm); color: var(--danger); margin: 0;"
              >Upload failed — please try again.</p>
            </div>
          </PiCard>
        </template>

        <!-- Step 4: Documents -->
        <template v-else-if="step === 4">
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-3);">Upload documents</h1>
          <p class="t-secondary" style="font-size: var(--text-base); margin-bottom: var(--space-5); max-width: 560px;">
            Optional. Anything you upload is read into your brain so the platform understands your context. Files stay on your server.
          </p>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--space-4);">
            <PiCard v-for="(z, idx) in docZones" :key="z.name">
              <div style="display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2);">
                <span style="color: var(--text-secondary); display: flex;">
                  <PIIcon :name="z.icon" :size="18" />
                </span>
                <span style="font-family: var(--font-display); font-weight: 500;">{{ z.name }}</span>
              </div>
              <p class="t-secondary" style="font-size: var(--text-sm); margin-bottom: var(--space-3); margin-top: 0;">{{ z.desc }}</p>
              <UploadZone
                :compact="true"
                title="Drop or click"
                :hint="`Accepted: ${z.fmt}`"
                @files="(files) => handleDocFiles(idx, files)"
              />
              <p
                v-if="z.state === 'uploading'"
                style="font-size: var(--text-xs); color: var(--text-tertiary); margin-top: var(--space-2); margin-bottom: 0;"
              >Uploading…</p>
              <p
                v-else-if="z.state === 'error'"
                style="font-size: var(--text-xs); color: var(--danger); margin-top: var(--space-2); margin-bottom: 0;"
              >Upload failed — please try again.</p>
            </PiCard>
          </div>
        </template>

        <!-- Step 5: Complete -->
        <template v-else-if="step === 5">
          <div style="display: flex; margin-bottom: var(--space-5);">
            <BrainPulse :size="56" :slow="true" aria-hidden="true" />
          </div>
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-5);">Your brain is ready.</h1>
          <div style="display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-5);">
            <div
              v-for="(item, i) in CHECK_ITEMS"
              :key="i"
              style="display: flex; align-items: center; gap: var(--space-3); transition: opacity .3s var(--ease), transform .3s var(--ease);"
              :style="{
                opacity: i < shownCount ? 1 : 0,
                transform: i < shownCount ? 'none' : 'translateY(8px)',
              }"
            >
              <span style="color: var(--success); display: flex;">
                <PIIcon name="check" :size="18" />
              </span>
              <span style="font-size: var(--text-base);">{{ item }}</span>
            </div>
          </div>
          <p class="t-secondary" style="font-size: var(--text-sm);">Your first content will be ready in a few minutes.</p>
        </template>

        <!-- Footer -->
        <div style="display: flex; align-items: center; justify-content: flex-end; gap: var(--space-4); margin-top: var(--space-8);">
          <a
            v-if="showSkip"
            href="#"
            class="t-secondary"
            style="font-size: var(--text-sm);"
            @click.prevent="skip"
          >Skip this step</a>
          <PiButton variant="cta" iconRight="arrowRight" @click="advance">
            {{ ctaLabel }}
          </PiButton>
        </div>

      </div>
    </div>
  </div>
</template>
