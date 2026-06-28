<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PiCard from '../ui/PiCard.vue'
import PiButton from '../ui/PiButton.vue'
import StatusPill from '../ui/StatusPill.vue'
import ConfirmModal from '../ui/ConfirmModal.vue'
import { useBankLink } from '../../composables/useBankLink'
import { useToast } from '../ui/useToast'

const toast = useToast()
const { status, institutions, loading, error, loadStatus, loadInstitutions, connect, syncNow, disconnect } = useBankLink()

const picking = ref(false)
const selectedId = ref('')
const confirmDisconnect = ref(false)

onMounted(async () => {
  await loadStatus()
  // Returning from the bank consent redirect → surface the outcome + refresh.
  const params = new URLSearchParams(window.location.search)
  if (params.get('bank_connected')) {
    toast('Bank connected — your statements will refresh automatically.', 'success')
    cleanQuery()
  } else if (params.get('bank_error')) {
    toast('Bank connection was cancelled or failed. Please try again.', 'error')
    cleanQuery()
  }
})

function cleanQuery() {
  const url = new URL(window.location.href)
  url.searchParams.delete('bank_connected')
  url.searchParams.delete('bank_error')
  window.history.replaceState({}, '', url.toString())
}

const connected = computed(() => status.value?.connected === true)
const hasError = computed(() => status.value?.status === 'error')
const configured = computed(() => status.value?.configured !== false)

const lastSyncLabel = computed(() => {
  const ts = status.value?.last_sync_at
  if (!ts) return null
  return new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
})

const balanceLabel = computed(() => {
  const b = status.value?.last_balance
  if (b == null) return null
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'EUR' }).format(b)
})

// PSD2 consent lasts ~90 days; warn the user when it's close to expiring.
const reconsentSoon = computed(() => {
  const ts = status.value?.consent_expires_at
  if (!ts) return false
  const days = (new Date(ts).getTime() - Date.now()) / 86_400_000
  return days < 14
})

async function openPicker() {
  picking.value = true
  if (!institutions.value.length) await loadInstitutions('de')
}

async function onConnect() {
  if (!selectedId.value) return
  await connect(selectedId.value)
  // connect() redirects the browser; if it returned, surface any error.
  if (error.value) toast(error.value, 'error')
}

async function onSync() {
  const ok = await syncNow()
  toast(ok ? 'Bank synced — your brain is up to date.' : (error.value || 'Sync failed.'), ok ? 'success' : 'error')
}

async function onDisconnect() {
  confirmDisconnect.value = false
  await disconnect()
  toast('Bank disconnected. Your past statements stay in your brain.', 'success')
  picking.value = false
  selectedId.value = ''
}
</script>

<template>
  <PiCard v-if="configured" style="margin-bottom: var(--space-5);">
    <!-- Connected -->
    <template v-if="connected">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); flex-wrap: wrap;">
        <div>
          <div style="display: flex; align-items: center; gap: var(--space-2);">
            <h3 style="font-size: var(--text-base); margin: 0;">{{ status?.institution_name || 'Your bank' }}</h3>
            <StatusPill :kind="hasError ? 'attention' : 'good'">{{ hasError ? 'Sync issue' : 'Connected' }}</StatusPill>
          </div>
          <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-2);">
            <template v-if="balanceLabel">Balance {{ balanceLabel }} · </template>
            <template v-if="lastSyncLabel">Last synced {{ lastSyncLabel }}</template>
            <template v-else>Not synced yet</template>
          </p>
          <p v-if="hasError && status?.last_error" style="font-size: var(--text-sm); color: var(--danger); margin-top: var(--space-2);">{{ status.last_error }}</p>
          <p v-if="reconsentSoon" style="font-size: var(--text-sm); color: var(--warning); margin-top: var(--space-2);">
            Your bank consent is expiring soon — reconnect to keep daily syncing.
          </p>
        </div>
        <div style="display: flex; gap: var(--space-2); flex-wrap: wrap;">
          <PiButton variant="secondary" icon="refresh" :loading="loading" @click="onSync">Sync now</PiButton>
          <PiButton variant="ghost" @click="confirmDisconnect = true">Disconnect</PiButton>
        </div>
      </div>
    </template>

    <!-- Not connected: picker -->
    <template v-else>
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); flex-wrap: wrap;">
        <div style="max-width: 42ch;">
          <h3 style="font-size: var(--text-base); margin: 0;">Connect your bank</h3>
          <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-2);">
            Link your Sparkasse or Volksbank once and your brain updates itself every day — no more monthly statement uploads. You log in at your own bank; we never see your banking password.
          </p>
        </div>
        <PiButton v-if="!picking" variant="cta" icon="plus" @click="openPicker">Connect bank</PiButton>
      </div>

      <div v-if="picking" style="margin-top: var(--space-4); display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center;">
        <select
          v-model="selectedId"
          :disabled="loading"
          aria-label="Choose your bank"
          style="flex: 1 1 240px; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); border: 1px solid var(--border-subtle); background: var(--bg-surface); color: var(--text-primary);"
        >
          <option value="" disabled>{{ loading ? 'Loading banks…' : 'Select your Sparkasse / Volksbank' }}</option>
          <option v-for="inst in institutions" :key="inst.id" :value="inst.id">{{ inst.name }}</option>
        </select>
        <PiButton variant="cta" :disabled="!selectedId" :loading="loading" @click="onConnect">Continue</PiButton>
      </div>
      <p v-if="error" style="font-size: var(--text-sm); color: var(--danger); margin-top: var(--space-3);">{{ error }}</p>
    </template>
  </PiCard>

  <ConfirmModal
    :open="confirmDisconnect"
    title="Disconnect your bank?"
    body="Daily syncing will stop. Statements already saved to your brain stay put."
    confirmLabel="Disconnect"
    danger
    @close="confirmDisconnect = false"
    @confirm="onDisconnect"
  />
</template>
