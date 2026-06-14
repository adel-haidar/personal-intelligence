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

// ── The export prompt (reproduced verbatim from the design handoff) ───────────
const PI_MEMORY_PROMPT = `Please write a complete personal profile based on everything you know
or remember about me from our conversation history.

Include the following sections, in plain structured text:
— Personal background (name, origin, location, languages)
— Career and professional life (role, company, skills, certifications, goals)
— Health and fitness (current status, goals, habits)
— Finances (approach to money, investments, goals — only what you know)
— Interests and hobbies
— Family and personal life
— Ongoing projects and priorities
— Anything else you know that would help an AI assistant serve me better

Format: use plain text with section headers. No markdown. No preamble.
No commentary — just the profile. Be thorough. This file is private.`

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

// Shared state across steps (mirrors the handoff's { file, intro, devices, docs }).
interface ImportedFile { name: string; chars: number; size: string }
const importedFile = ref<ImportedFile | null>(null)
const introText    = ref('')
const devicesCount = ref(0)
const docsCount    = ref(0)

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// Shared upload helper — files are indexed into the user's brain.
async function uploadToBrain(file: File): Promise<boolean> {
  try {
    const token = await requireAuth()
    const fd = new FormData()
    fd.append('files', file)
    const res = await fetch(`${API_BASE}/api/file`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    })
    return res.ok
  } catch {
    return false
  }
}

// ── step 2 — export AI memory ─────────────────────────────────────────────────
const PROVIDERS = ['Claude', 'ChatGPT', 'Gemini', 'Other'] as const
type Provider = typeof PROVIDERS[number]
const provider = ref<Provider>('Claude')
const copied   = ref(false)

async function copyPrompt(): Promise<void> {
  try { await navigator.clipboard?.writeText(PI_MEMORY_PROMPT) } catch { /* ignore */ }
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

const exportUploadState = ref<'idle' | 'uploading' | 'error'>('idle')

async function handleExportFiles(files: File[]): Promise<void> {
  const file = files[0]
  if (!file) return
  exportUploadState.value = 'uploading'

  // Compute a char count for the chip (best-effort for text-like files).
  let chars = Math.max(1, Math.round(file.size * 0.92))
  try {
    const text = await file.text()
    if (text) chars = text.length
  } catch { /* keep estimate */ }

  const ok = await uploadToBrain(file)
  if (ok) {
    importedFile.value = { name: file.name, chars, size: humanSize(file.size) }
    exportUploadState.value = 'idle'
  } else {
    exportUploadState.value = 'error'
  }
}

function clearImportedFile(): void {
  importedFile.value = null
}

// ── step 3 — introduction ─────────────────────────────────────────────────────
const introSaved = ref(false)
const introSavedHash = ref('')
let introTimer: ReturnType<typeof setTimeout> | null = null

function hashStr(s: string): string {
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
  introTimer = setTimeout(() => { saveIntro() }, 3000)
})

async function saveIntro(): Promise<void> {
  const text = introText.value.trim()
  if (!text) return
  const h = hashStr(text)
  if (h === introSavedHash.value) return
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
  } catch { /* best-effort */ }
}

onBeforeUnmount(() => {
  if (introTimer) clearTimeout(introTimer)
})

// ── step 4 — connect devices + documents ──────────────────────────────────────
const DEVICE_TABS = ['Apple Watch', 'Samsung Health', 'Garmin', 'Smart Scale', 'Other'] as const
type DeviceTab = typeof DEVICE_TABS[number]
const deviceTab = ref<DeviceTab>('Apple Watch')

const ICON_FOR: Record<DeviceTab, string> = {
  'Apple Watch': 'watch',
  'Samsung Health': 'watch',
  'Garmin': 'device',
  'Smart Scale': 'scale',
  'Other': 'plus',
}

const deviceUploadState = ref<'idle' | 'uploading' | 'error'>('idle')
watch(deviceTab, () => { deviceUploadState.value = 'idle' })

async function handleDeviceFiles(files: File[]): Promise<void> {
  const file = files[0]
  if (!file) return
  deviceUploadState.value = 'uploading'
  const ok = await uploadToBrain(file)
  if (ok) { devicesCount.value += 1; deviceUploadState.value = 'idle' }
  else deviceUploadState.value = 'error'
}

interface DocZone {
  icon: string
  name: string
  desc: string
  fmt: string
  state: 'idle' | 'uploading' | 'error'
}
const docZones = ref<DocZone[]>([
  { icon: 'finances', name: 'Financial documents', desc: 'Bank statements, payslips, portfolios.',       fmt: 'PDF, CSV, XLSX', state: 'idle' },
  { icon: 'file',     name: 'CV & career',         desc: 'Resume, certifications, performance reviews.',   fmt: 'PDF, DOCX',     state: 'idle' },
  { icon: 'health',   name: 'Medical records',     desc: 'Blood tests, doctor reports, prescriptions.',    fmt: 'PDF, images',   state: 'idle' },
])

async function handleDocFiles(idx: number, files: File[]): Promise<void> {
  const file = files[0]
  if (!file) return
  docZones.value[idx].state = 'uploading'
  const ok = await uploadToBrain(file)
  if (ok) { docsCount.value += 1; docZones.value[idx].state = 'idle' }
  else docZones.value[idx].state = 'error'
}

// ── step 5 — complete (conditional checklist) ─────────────────────────────────
const checkItems = computed(() => [
  { label: 'Brain created',          show: true },
  { label: 'Introduction saved',     show: !!introText.value.trim() },
  { label: 'Memory file imported',   show: !!importedFile.value },
  { label: 'Devices connected',      show: devicesCount.value > 0 },
  { label: 'Documents uploaded',     show: docsCount.value > 0 },
].filter(i => i.show))

const shownCount = ref(0)
let checkTimers: ReturnType<typeof setTimeout>[] = []

function runCheckAnimation(): void {
  checkTimers.forEach(clearTimeout)
  checkTimers = []
  shownCount.value = 0
  checkItems.value.forEach((_, i) => {
    checkTimers.push(setTimeout(() => { shownCount.value = Math.max(shownCount.value, i + 1) }, 200 * (i + 1)))
  })
}

// ── navigation ─────────────────────────────────────────────────────────────────
async function patchOnboarding(patch: { onboarding_step?: number; onboarding_completed?: boolean }): Promise<void> {
  try {
    const token = await requireAuth()
    await fetch(`${API_BASE}/api/auth/onboarding`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(patch),
    })
  } catch { /* best-effort */ }
}

async function advance(): Promise<void> {
  // Step 3: flush intro save before moving on.
  if (step.value === 3) {
    if (introTimer) { clearTimeout(introTimer); introTimer = null }
    await saveIntro()
  }

  if (step.value < TOTAL) {
    const next = step.value + 1
    step.value = next
    patchOnboarding({ onboarding_step: next })
    if (next === TOTAL) runCheckAnimation()
  } else {
    await patchOnboarding({ onboarding_completed: true })
    router.replace('/overview')
  }
}

function skip(): void {
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

const skipLabel = computed(() => ({
  2: 'Skip — I’ll add memories manually later',
  3: 'Skip — I’ll add this later',
  4: 'Skip — connect devices later',
}[step.value as 2 | 3 | 4]))

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
            style="font-size: var(--text-md); line-height: 1.8; color: var(--text-secondary); display: flex; flex-direction: column; gap: var(--space-3); max-width: 620px;"
          >
            <p>
              At the center of Private Internet is your
              <strong style="color: var(--text-primary);">brain</strong>
              — a private knowledge base that grows as you add notes, upload documents, and connect devices. Everything you build reads from it.
            </p>
            <p>Nothing is sold. Nothing leaves your server. The more you share with your brain, the more personal everything becomes.</p>
            <p>The next few steps set it up. It takes a few minutes, and you can change everything later.</p>
          </div>
        </template>

        <!-- Step 2: Export your AI memory -->
        <template v-else-if="step === 2">
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-3);">Bring what your AI already knows about you.</h1>
          <div
            class="t-secondary"
            style="font-size: var(--text-base); line-height: 1.65; max-width: 640px; margin-bottom: var(--space-5); display: flex; flex-direction: column; gap: var(--space-2);"
          >
            <p>If you've been using ChatGPT, Claude, Gemini or another AI assistant, it already knows a lot about you from your conversations. Use the prompt below to make it write everything it knows — then upload that file here. Your brain will start smart instead of blank.</p>
            <p>You can also skip this and write manually in the next step. The more you add, the more personalized everything becomes.</p>
          </div>

          <div style="margin-bottom: var(--space-4);">
            <Pills
              :options="[...PROVIDERS]"
              :modelValue="provider"
              @update:modelValue="(v) => (provider = v as Provider)"
            />
          </div>

          <div class="pi-prompt" style="margin-bottom: var(--space-4);">
            <div class="pi-prompt__bar">
              <span class="pi-prompt__tag">Prompt for {{ provider }}</span>
              <PiButton
                variant="ghost"
                size="compact"
                :icon="copied ? 'check' : 'copy'"
                :style="copied ? { color: 'var(--success)' } : undefined"
                @click="copyPrompt"
              >{{ copied ? 'Copied' : 'Copy prompt' }}</PiButton>
            </div>
            <pre class="pi-prompt__pre">{{ PI_MEMORY_PROMPT }}</pre>
          </div>

          <div class="pi-callout" style="margin-bottom: var(--space-6);">
            <span style="color: var(--brain-amber); display: flex; flex: 0 0 auto; margin-top: 1px;"><PIIcon name="file" :size="16" /></span>
            <span>Once your AI generates the profile, save it as a <span class="t-mono" style="font-size: 0.92em;">.txt</span> or <span class="t-mono" style="font-size: 0.92em;">.md</span> file. You'll upload it just below.</span>
          </div>

          <div class="pi-or" style="margin-bottom: var(--space-6);">or</div>

          <!-- Imported file chip OR upload card -->
          <div v-if="importedFile" class="pi-filechip">
            <span style="color: var(--success); display: flex; flex: 0 0 auto;"><PIIcon name="check" :size="18" /></span>
            <div style="flex: 1; min-width: 0;">
              <div class="pi-filechip__name">{{ importedFile.name }}</div>
              <div class="pi-filechip__meta">{{ importedFile.chars.toLocaleString() }} chars · {{ importedFile.size }}</div>
            </div>
            <PiButton variant="ghost" size="compact" @click="clearImportedFile">Remove</PiButton>
          </div>
          <PiCard v-else>
            <p class="t-secondary" style="font-size: var(--text-sm); line-height: 1.65; margin: 0 0 var(--space-3);">
              Already have notes, a CV, or a document about yourself? Upload that instead — any
              <span class="t-mono" style="font-size: 0.92em;">.txt</span>,
              <span class="t-mono" style="font-size: 0.92em;">.md</span>, or
              <span class="t-mono" style="font-size: 0.92em;">.pdf</span> file works.
            </p>
            <UploadZone
              :compact="true"
              :title="exportUploadState === 'uploading' ? 'Uploading…' : 'Upload a file'"
              hint="Accepted: .txt, .md, .pdf"
              accept=".txt,.md,.pdf"
              @files="handleExportFiles"
            />
            <p v-if="exportUploadState === 'error'" style="font-size: var(--text-sm); color: var(--danger); margin: var(--space-2) 0 0;">
              Upload failed — please try again.
            </p>
          </PiCard>
        </template>

        <!-- Step 3: Introduction -->
        <template v-else-if="step === 3">
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-3);">Tell your brain who you are.</h1>
          <p class="t-secondary" style="font-size: var(--text-base); line-height: 1.65; margin-bottom: var(--space-5); max-width: 620px;">
            Write in any language. There's no format. Cover whatever feels relevant — your job, your goals, your health situation, your interests, what's on your mind. The more detail you add, the smarter everything becomes.
          </p>

          <div v-if="importedFile" class="pi-filechip" style="margin-bottom: var(--space-4);">
            <span style="color: var(--success); display: flex; flex: 0 0 auto;"><PIIcon name="file" :size="16" /></span>
            <div style="flex: 1; min-width: 0;">
              <div class="pi-filechip__name">{{ importedFile.name }}</div>
              <div class="pi-filechip__meta">{{ importedFile.chars.toLocaleString() }} chars imported · already in your brain</div>
            </div>
            <PiButton variant="ghost" size="compact" @click="clearImportedFile">Delete</PiButton>
          </div>
          <p v-if="importedFile" class="t-secondary" style="font-size: var(--text-sm); margin-bottom: var(--space-3);">
            This content is already in your brain. Add anything the file missed.
          </p>

          <div style="position: relative;">
            <PiTextarea
              :serif="true"
              v-model="introText"
              placeholder="My name is… I work as… I'm currently focused on… I care about…"
              style="min-height: 200px; padding-bottom: 40px;"
            />
            <div style="position: absolute; right: 12px; bottom: 12px; display: flex; gap: var(--space-3); align-items: center;">
              <span v-if="introSaved" class="t-mono" style="font-size: var(--text-xs); color: var(--brain-amber);">&#10003; Saved</span>
              <span class="pi-counter">{{ introText.length }} chars</span>
            </div>
          </div>
        </template>

        <!-- Step 4: Connect devices & upload documents -->
        <template v-else-if="step === 4">
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-3);">Connect devices and upload documents.</h1>
          <p class="t-secondary" style="font-size: var(--text-base); line-height: 1.65; margin-bottom: var(--space-6); max-width: 620px;">
            Optional, and you can do this any time. Anything you add here becomes part of your brain — there's no live account link, only files you choose to share.
          </p>

          <!-- Devices -->
          <div class="pi-sub-label">Health devices</div>
          <div style="margin-bottom: var(--space-4);">
            <Pills
              :options="[...DEVICE_TABS]"
              :modelValue="deviceTab"
              @update:modelValue="(v) => (deviceTab = v as DeviceTab)"
            />
          </div>
          <PiCard style="margin-bottom: var(--space-8);">
            <EmptyState
              v-if="deviceTab === 'Other'"
              icon="plus"
              title="More devices soon"
              desc="Fitbit, Oura, and Withings are next. For now, upload any export file your device produces below."
            />
            <div v-else style="display: flex; flex-direction: column; gap: var(--space-4);">
              <div style="display: flex; align-items: center; gap: var(--space-3);">
                <span class="pi-device__ic"><PIIcon :name="ICON_FOR[deviceTab]" :size="20" /></span>
                <div style="font-family: var(--font-display); font-weight: 500;">{{ deviceTab }}</div>
              </div>
              <ol class="t-secondary" style="font-size: var(--text-sm); padding-left: var(--space-4); line-height: 1.8; margin: 0;">
                <li>Open the device's companion app</li>
                <li>Find Export or Download your data</li>
                <li>Upload the file below</li>
              </ol>
              <UploadZone
                :compact="true"
                :title="`Upload ${deviceTab} export`"
                hint="Processed on your server only"
                @files="handleDeviceFiles"
              />
              <p v-if="deviceUploadState === 'error'" style="font-size: var(--text-sm); color: var(--danger); margin: 0;">
                Upload failed — please try again.
              </p>
            </div>
          </PiCard>

          <!-- Documents -->
          <div class="pi-sub-label">Documents</div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-5);">
            <PiCard v-for="(z, idx) in docZones" :key="z.name">
              <div style="display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2);">
                <span style="color: var(--text-secondary); display: flex;"><PIIcon :name="z.icon" :size="18" /></span>
                <span style="font-family: var(--font-display); font-weight: 500; font-size: var(--text-sm);">{{ z.name }}</span>
              </div>
              <p class="t-secondary" style="font-size: var(--text-sm); margin: 0 0 var(--space-3);">{{ z.desc }}</p>
              <UploadZone
                :compact="true"
                title="Drop or click"
                :hint="z.fmt"
                @files="(files) => handleDocFiles(idx, files)"
              />
              <p v-if="z.state === 'uploading'" style="font-size: var(--text-xs); color: var(--text-tertiary); margin: var(--space-2) 0 0;">Uploading…</p>
              <p v-else-if="z.state === 'error'" style="font-size: var(--text-xs); color: var(--danger); margin: var(--space-2) 0 0;">Upload failed — please try again.</p>
            </PiCard>
          </div>

          <p class="t-tertiary" style="font-size: var(--text-sm); line-height: 1.6;">
            All files are stored only on your server. You can delete them at any time from the Brain section.
          </p>
        </template>

        <!-- Step 5: Complete -->
        <template v-else-if="step === 5">
          <div style="display: flex; margin-bottom: var(--space-5);">
            <BrainPulse :size="56" :slow="true" aria-hidden="true" />
          </div>
          <h1 style="font-size: var(--text-xl); margin-bottom: var(--space-5);">Your brain is ready.</h1>
          <div style="display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-6);">
            <div
              v-for="(item, i) in checkItems"
              :key="item.label"
              style="display: flex; align-items: center; gap: var(--space-3); transition: opacity .3s var(--ease), transform .3s var(--ease);"
              :style="{
                opacity: i < shownCount ? 1 : 0,
                transform: i < shownCount ? 'none' : 'translateY(8px)',
              }"
            >
              <span style="color: var(--success); display: flex;"><PIIcon name="check" :size="18" /></span>
              <span style="font-size: var(--text-base);">{{ item.label }}</span>
            </div>
          </div>
          <p class="t-serif" style="color: var(--text-secondary); font-size: var(--text-md); font-style: italic; max-width: 540px; line-height: 1.7;">
            Everything you add from here makes the platform more specifically yours.
          </p>
        </template>

        <!-- Footer -->
        <div style="display: flex; align-items: center; justify-content: flex-end; gap: var(--space-5); margin-top: var(--space-8);">
          <a
            v-if="skipLabel"
            href="#"
            class="t-secondary"
            style="font-size: var(--text-sm);"
            @click.prevent="skip"
          >{{ skipLabel }}</a>
          <PiButton variant="cta" iconRight="arrowRight" @click="advance">
            {{ ctaLabel }}
          </PiButton>
        </div>

      </div>
    </div>
  </div>
</template>
