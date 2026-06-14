<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import PageHead from '../components/ui/PageHead.vue'
import Avatar from '../components/ui/Avatar.vue'
import PiButton from '../components/ui/PiButton.vue'
import PiInput from '../components/ui/PiInput.vue'
import PiSelect from '../components/ui/PiSelect.vue'
import Badge from '../components/ui/Badge.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'
import ConfirmModal from '../components/ui/ConfirmModal.vue'
import { useToast } from '../components/ui/useToast'
import { useTheme } from '../composables/useTheme'
import { useBilling } from '../composables/useBilling'
import { useBrainOrganiser } from '../composables/useBrainOrganiser'
import { requireAuth, logout } from '../composables/useAuth'
import { API_BASE } from '../config/env'

const router = useRouter()
const toast = useToast()
const { theme } = useTheme()
const { status: billing, fetchStatus, openPortal } = useBilling()
const {
  status: organiserStatus,
  running: organiserRunning,
  organise: runOrganise,
  fetchStatus: fetchOrganiserStatus,
} = useBrainOrganiser()

const organiserLastRunText = computed(() => {
  const lr = organiserStatus.value?.last_run
  if (!lr || !lr.completed_at) return 'Never run'
  const date = new Date(lr.completed_at).toLocaleDateString()
  return `Last run: ${date} — ${lr.duplicates_removed} duplicates removed, ${lr.clusters_merged} merged`
})

async function organiseNow() {
  const r = await runOrganise()
  if (r.ok || r.conflict) {
    router.push('/memory') // brain page (/memory) shows the sleeping banner
  } else {
    toast(r.error || 'Could not start the organiser', 'error')
  }
}

const SECTIONS = ['Profile', 'Privacy & data', 'Notifications', 'About'] as const
type Section = typeof SECTIONS[number]
const section = ref<Section>('Profile')

// ── Profile ───────────────────────────────────────────────────────────────────
const LANGS = [
  { code: 'en', label: 'English' },
  { code: 'de', label: 'Deutsch' },
  { code: 'fr', label: 'Français' },
  { code: 'ar', label: 'العربية' },
  { code: 'sv', label: 'Svenska' },
]
const email = ref('')
const displayName = ref('')
const originalName = ref('')
const language = ref('English')
const savingProfile = ref(false)

async function authHeaders(): Promise<Record<string, string>> {
  const token = await requireAuth()
  return { Authorization: `Bearer ${token}` }
}

onMounted(async () => {
  fetchStatus()
  fetchOrganiserStatus()
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, { headers: await authHeaders() })
    if (res.ok) {
      const { user } = await res.json()
      email.value = user.email ?? ''
      displayName.value = user.display_name ?? ''
      originalName.value = displayName.value
      language.value = LANGS.find(l => l.code === user.language_preference)?.label ?? 'English'
    }
  } catch { /* ignore */ }
})

const nameDirty = computed(() => !!displayName.value.trim() && displayName.value !== originalName.value)

async function saveProfile() {
  savingProfile.value = true
  try {
    const res = await fetch(`${API_BASE}/api/auth/profile`, {
      method: 'PATCH',
      headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName.value.trim() }),
    })
    if (res.ok) { originalName.value = displayName.value.trim(); toast('Profile updated', 'success') }
    else toast('Could not update profile', 'error')
  } catch { toast('Could not update profile', 'error') } finally { savingProfile.value = false }
}

async function changeLanguage(label: string) {
  language.value = label
  const code = LANGS.find(l => l.label === label)?.code ?? 'en'
  try {
    await fetch(`${API_BASE}/api/auth/profile`, {
      method: 'PATCH',
      headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
      body: JSON.stringify({ language_preference: code }),
    })
    toast('Language updated', 'success')
  } catch { /* best-effort */ }
}

// ── Privacy & data ──────────────────────────────────────────────────────────────
const exporting = ref(false)
async function exportData() {
  exporting.value = true
  try {
    const res = await fetch(`${API_BASE}/api/auth/export`, { headers: await authHeaders() })
    if (!res.ok) throw new Error()
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'private-internet-export.json'
    a.click()
    URL.revokeObjectURL(url)
    toast('Export downloaded', 'success')
  } catch { toast('Could not export your data', 'error') } finally { exporting.value = false }
}

const confirmClear = ref(false)
async function clearBrain() {
  confirmClear.value = false
  try {
    const res = await fetch(`${API_BASE}/api/auth/clear-brain`, { method: 'POST', headers: await authHeaders() })
    if (res.ok) { const { deleted } = await res.json(); toast(`Cleared ${deleted} memories`, 'warning') }
    else toast('Could not clear your brain', 'error')
  } catch { toast('Could not clear your brain', 'error') }
}

const delText = ref('')
const deleting = ref(false)
async function deleteAccount() {
  deleting.value = true
  try {
    const res = await fetch(`${API_BASE}/api/auth/account`, {
      method: 'DELETE',
      headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: 'DELETE' }),
    })
    if (res.ok) { toast('Account deleted', 'warning'); logout(); router.replace('/login') }
    else toast('Could not delete account', 'error')
  } catch { toast('Could not delete account', 'error') } finally { deleting.value = false }
}

const showBilling = computed(() => billing.value?.billing_enabled)
</script>

<template>
  <div style="max-width: var(--content-dashboard); margin: 0 auto;">
    <PageHead title="Settings" desc="Manage your profile, your data, and how Private Internet behaves." />

    <div class="pi-settings-grid" style="display: grid; grid-template-columns: 180px 1fr; gap: var(--space-8); align-items: start;">
      <nav style="display: flex; flex-direction: column; gap: 2px;">
        <button
          v-for="s in SECTIONS" :key="s"
          :style="{
            textAlign: 'left', padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-sm)',
            fontSize: 'var(--text-sm)', fontFamily: 'var(--font-display)', fontWeight: 500, border: 'none', cursor: 'pointer',
            background: section === s ? 'var(--accent-surface)' : 'transparent',
            color: section === s ? 'var(--accent-hover)' : 'var(--text-secondary)',
          }"
          @click="section = s"
        >{{ s }}</button>
      </nav>

      <div>
        <!-- Profile -->
        <div v-if="section === 'Profile'" style="display: flex; flex-direction: column; gap: var(--space-5); max-width: 460px;">
          <div style="display: flex; align-items: center; gap: var(--space-4);">
            <Avatar :name="displayName || email" :size="56" />
            <PiButton variant="secondary" size="compact" @click="toast('Photo upload is coming soon')">Upload photo</PiButton>
          </div>

          <div class="pi-field">
            <label class="pi-label">Display name</label>
            <PiInput v-model="displayName" placeholder="Your name" />
          </div>
          <div>
            <PiButton variant="primary" size="compact" :disabled="!nameDirty" :loading="savingProfile" @click="saveProfile">Save</PiButton>
          </div>

          <div class="pi-field">
            <label class="pi-label">Email</label>
            <PiInput :modelValue="email" disabled />
            <span class="pi-field__hint">Read-only</span>
          </div>

          <div class="pi-field">
            <label class="pi-label">Language</label>
            <PiSelect :options="LANGS.map(l => l.label)" :modelValue="language" @update:modelValue="changeLanguage" />
          </div>

          <div>
            <div class="pi-label" style="margin-bottom: var(--space-2);">Appearance</div>
            <div style="display: flex; align-items: center; gap: var(--space-3);">
              <ModeToggle />
              <span class="t-tertiary" style="font-size: var(--text-sm);">Currently {{ theme }}</span>
            </div>
          </div>
        </div>

        <!-- Privacy & data -->
        <div v-else-if="section === 'Privacy & data'" style="display: flex; flex-direction: column; max-width: 560px;">
          <div class="pi-set-row">
            <div>
              <div class="pi-set-row__title">Export all my data</div>
              <div class="pi-set-row__desc">Download everything in your brain as a JSON archive.</div>
            </div>
            <PiButton variant="secondary" size="compact" icon="upload" :loading="exporting" @click="exportData">Export</PiButton>
          </div>

          <div class="pi-set-row">
            <div>
              <div class="pi-set-row__title" style="color: var(--warning);">Clear my brain</div>
              <div class="pi-set-row__desc">Remove all memories. Modules will reset to empty. This cannot be undone.</div>
            </div>
            <PiButton variant="secondary" size="compact" style="border-color: var(--warning); color: var(--warning);" @click="confirmClear = true">Clear</PiButton>
          </div>

          <div class="pi-set-row">
            <div>
              <div class="pi-set-row__title">Organise brain memory</div>
              <div class="pi-set-row__desc">Remove duplicates and merge related memories.</div>
              <div class="pi-set-row__desc t-mono" style="font-size: var(--text-xs); margin-top: 4px;">{{ organiserLastRunText }}</div>
            </div>
            <PiButton variant="secondary" size="compact" :loading="organiserRunning" :disabled="organiserRunning" @click="organiseNow">
              Organise now
            </PiButton>
          </div>

          <div v-if="showBilling" class="pi-set-row">
            <div>
              <div class="pi-set-row__title">Subscription</div>
              <div class="pi-set-row__desc">Manage your membership, payment method, or cancel — handled securely by Stripe.</div>
            </div>
            <PiButton variant="secondary" size="compact" @click="openPortal().catch(() => toast('No billing account yet', 'error'))">Manage</PiButton>
          </div>

          <div class="pi-set-row">
            <div>
              <div class="pi-set-row__title" style="color: var(--danger);">Delete my account</div>
              <div class="pi-set-row__desc">Permanently removes all data from this server. Type DELETE to confirm.</div>
            </div>
            <div style="display: flex; gap: var(--space-2);">
              <PiInput v-model="delText" placeholder="DELETE" style="width: 120px;" />
              <PiButton variant="danger" size="compact" :disabled="delText !== 'DELETE'" :loading="deleting" @click="deleteAccount">Delete</PiButton>
            </div>
          </div>
        </div>

        <!-- Notifications -->
        <div v-else-if="section === 'Notifications'" style="display: flex; flex-direction: column; gap: var(--space-4); max-width: 460px;">
          <div
            v-for="n in ['New Pulse posts', 'Signal video ready', 'Health sync reminders', 'Weekly brain summary']" :key="n"
            style="display: flex; align-items: center; justify-content: space-between; opacity: 0.6;"
          >
            <span style="font-size: var(--text-base);">{{ n }}</span>
            <Badge variant="outlined">Coming soon</Badge>
          </div>
        </div>

        <!-- About -->
        <div v-else style="display: flex; flex-direction: column; max-width: 460px;">
          <div class="pi-set-row">
            <div class="pi-set-row__title">Version</div>
            <span class="t-mono t-secondary" style="font-size: var(--text-sm);">4.0.0</span>
          </div>
          <div class="pi-set-row">
            <div class="pi-set-row__title">Source</div>
            <a href="https://github.com/adel-haidar/personal-intelligence" target="_blank" rel="noopener" style="font-size: var(--text-sm);">View on GitHub →</a>
          </div>
          <div class="pi-set-row">
            <div>
              <div class="pi-set-row__title">Hosting</div>
              <div class="pi-set-row__desc">Runs on your own server. Your data stays with you.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <ConfirmModal
    :open="confirmClear" danger confirmLabel="Clear my brain"
    title="Clear your entire brain?"
    body="This removes every memory. Pulse, Signal and the other modules will reset to empty. This cannot be undone."
    @close="confirmClear = false" @confirm="clearBrain"
  />
</template>

<style scoped>
.pi-set-row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);
  padding: var(--space-3) 0; border-bottom: 1px solid var(--border-subtle);
}
.pi-set-row__title { font-family: var(--font-display); font-weight: 500; font-size: var(--text-base); color: var(--text-primary); }
.pi-set-row__desc { font-size: var(--text-sm); color: var(--text-secondary); margin-top: 2px; }

@media (max-width: 768px) {
  .pi-settings-grid { grid-template-columns: 1fr !important; }
}
</style>
