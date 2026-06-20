<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import type { JobMatch, JobApplication } from '../../types/jobs'
import {
  startApplication,
  getApplicationByMatch,
  getApplication,
  getApplicationPdf,
  submitApplicationFeedback,
  applyApplication,
} from '../../api/jobs'

const props = defineProps<{ match: JobMatch }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'applied'): void }>()

const app = ref<JobApplication | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const pdfUrl = ref<string | null>(null)
const feedback = ref('')
const busy = ref(false)          // apply / feedback submit in flight
const revising = ref(false)      // true while a feedback-driven regeneration runs

let pollTimer: ReturnType<typeof setInterval> | null = null
let pollCount = 0
const MAX_POLLS = 240            // 10 minutes at 2.5s

const isGenerating = computed(() => app.value?.status === 'generating')
const isReady = computed(() => app.value?.status === 'ready' && !!pdfUrl.value)
const isFailed = computed(() => app.value?.status === 'failed')

const generatingMessage = computed(() =>
  revising.value
    ? 'Applying your feedback — you can close this window and come back later. We’ll save the updated application so you can revisit it.'
    : 'Preparing your application — the agent is reading the job and your Brain, writing your cover letter, and assembling your documents. This can take a minute.',
)

const downloadName = computed(() => {
  const safe = (s: string) => (s || '').replace(/[^\w.-]+/g, '_').slice(0, 60)
  return `Application_${safe(props.match.company)}_${safe(props.match.title)}.pdf`
})

function stopPolling(): void {
  if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null }
  pollCount = 0
}

function revokePdf(): void {
  if (pdfUrl.value) { URL.revokeObjectURL(pdfUrl.value); pdfUrl.value = null }
}

async function loadPdf(appId: number): Promise<void> {
  try {
    const blob = await getApplicationPdf(appId)
    revokePdf()
    pdfUrl.value = URL.createObjectURL(blob)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load the application PDF'
  }
}

function startPolling(appId: number): void {
  stopPolling()
  pollTimer = setInterval(async () => {
    pollCount++
    if (pollCount > MAX_POLLS) {
      stopPolling()
      error.value = 'The application is taking longer than expected. Try again later.'
      return
    }
    try {
      const next = await getApplication(appId)
      app.value = next
      if (next.status === 'ready') {
        stopPolling()
        revising.value = false
        await loadPdf(appId)
      } else if (next.status === 'failed') {
        stopPolling()
        revising.value = false
        error.value = next.error || 'The application could not be generated.'
      }
    } catch {
      // transient — keep polling
    }
  }, 2500)
}

async function init(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    let existing = await getApplicationByMatch(props.match.id)
    if (existing === null) {
      const started = await startApplication(props.match.id)
      existing = { ...emptyApplication(started.application_id), status: 'generating' }
    }
    app.value = existing
    if (existing.status === 'generating') {
      startPolling(existing.id)
    } else if (existing.status === 'ready') {
      await loadPdf(existing.id)
    } else if (existing.status === 'failed') {
      error.value = existing.error || 'The application could not be generated.'
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not start the application'
  } finally {
    loading.value = false
  }
}

function emptyApplication(id: number): JobApplication {
  return {
    id, match_id: props.match.id, status: 'generating', cover_letter: null,
    manifest: null, feedback_history: [], error: null, iterations: 0,
    has_pdf: false, updated_at: null, created_at: null,
  }
}

async function onRegenerate(): Promise<void> {
  error.value = null
  try {
    const started = await startApplication(props.match.id)
    app.value = emptyApplication(started.application_id)
    revising.value = false
    startPolling(started.application_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not restart the application'
  }
}

async function onSendFeedback(): Promise<void> {
  const text = feedback.value.trim()
  if (!text || !app.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    const res = await submitApplicationFeedback(app.value.id, text)
    feedback.value = ''
    revising.value = true
    revokePdf()
    app.value = { ...app.value, status: 'generating' }
    startPolling(res.application_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not submit feedback'
  } finally {
    busy.value = false
  }
}

function triggerDownload(): void {
  if (!pdfUrl.value) return
  const a = document.createElement('a')
  a.href = pdfUrl.value
  a.download = downloadName.value
  document.body.appendChild(a)
  a.click()
  a.remove()
}

async function onApply(): Promise<void> {
  if (!app.value || busy.value) return
  busy.value = true
  // Open the employer site immediately (still inside the click gesture so it is
  // not blocked) and save the application to the user's computer.
  if (props.match.job_url) window.open(props.match.job_url, '_blank', 'noopener')
  triggerDownload()
  try {
    await applyApplication(app.value.id)
    emit('applied')
    onClose()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not mark as applied'
  } finally {
    busy.value = false
  }
}

function onClose(): void {
  stopPolling()
  revokePdf()
  emit('close')
}

onMounted(init)
onBeforeUnmount(() => { stopPolling(); revokePdf() })
</script>

<template>
  <Teleport to="body">
  <div class="modal-backdrop" @click.self="onClose">
    <div class="modal" role="dialog" aria-modal="true" aria-label="Job application">
      <header class="modal-head">
        <div class="head-text">
          <h2 class="modal-title">Application</h2>
          <p class="modal-sub">{{ match.title }} · {{ match.company }}</p>
        </div>
        <button class="icon-btn" aria-label="Close" @click="onClose">✕</button>
      </header>

      <div class="modal-body">
        <!-- Generating / revising -->
        <div v-if="isGenerating || (loading && !app)" class="state-panel">
          <div class="pulse" aria-hidden="true">
            <span></span><span></span><span></span><span></span>
          </div>
          <p class="state-msg">{{ generatingMessage }}</p>
          <button class="btn btn-ghost" @click="onClose">Close and come back later</button>
        </div>

        <!-- Failed -->
        <div v-else-if="isFailed || (error && !isReady)" class="state-panel">
          <p class="state-msg error">{{ error || 'The application could not be generated.' }}</p>
          <button class="btn btn-secondary" @click="onRegenerate">Try again</button>
        </div>

        <!-- Ready: PDF viewer -->
        <template v-else-if="isReady">
          <iframe
            :src="pdfUrl!"
            class="pdf-frame"
            title="Application preview"
          ></iframe>

          <p v-if="error" class="inline-error">{{ error }}</p>

          <div class="feedback-block">
            <label class="feedback-label" for="app-feedback">
              Want changes? Tell the agent what to adjust
            </label>
            <textarea
              id="app-feedback"
              v-model="feedback"
              class="feedback-input"
              rows="3"
              :disabled="busy"
              placeholder="e.g. You forgot to add certificate XYZ, please update the application.
The CV has a wrong date — please correct it.
Adjust the cover letter by deleting sentence X and adding sentence Y."
            ></textarea>
            <div class="feedback-actions">
              <button
                class="btn btn-secondary"
                :disabled="busy || !feedback.trim()"
                @click="onSendFeedback"
              >
                Send feedback
              </button>
            </div>
          </div>
        </template>
      </div>

      <footer class="modal-foot">
        <button class="btn btn-ghost" :disabled="busy" @click="onClose">Cancel</button>
        <div class="foot-right">
          <button
            class="btn btn-secondary"
            :disabled="!isReady || busy"
            @click="triggerDownload"
          >
            Download application
          </button>
          <button
            class="btn btn-primary"
            :disabled="!isReady || busy"
            @click="onApply"
          >
            Apply
          </button>
        </div>
      </footer>
    </div>
  </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
}
.modal {
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg, 14px);
  box-shadow: var(--shadow-lg, 0 20px 50px rgba(0, 0, 0, 0.4));
  width: min(880px, 100%);
  height: min(90vh, 1000px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.modal-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.modal-sub {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 2px 0 0;
}
.icon-btn {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 16px;
  padding: 2px 6px;
  border-radius: var(--radius-sm, 8px);
}
.icon-btn:hover { color: var(--text-primary); background: var(--background-raised); }

.modal-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 20px;
  gap: 14px;
  overflow-y: auto;
}

.pdf-frame {
  flex: 1 1 auto;
  min-height: 380px;
  width: 100%;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  background: var(--background-raised);
}

.state-panel {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  text-align: center;
  padding: 40px 24px;
}
.state-msg {
  font-size: 14px;
  color: var(--text-secondary);
  max-width: 460px;
  line-height: 1.6;
  margin: 0;
}
.state-msg.error { color: var(--danger); }
.inline-error { font-size: 12px; color: var(--danger); margin: 0; }

/* Brain Pulse — 4 orbiting amber dots */
.pulse {
  position: relative;
  width: 44px;
  height: 44px;
}
.pulse span {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 8px;
  height: 8px;
  margin: -4px;
  border-radius: 50%;
  background: var(--brain-amber, #d99a3a);
  animation: orbit 1.4s linear infinite;
}
.pulse span:nth-child(2) { animation-delay: -0.35s; }
.pulse span:nth-child(3) { animation-delay: -0.70s; }
.pulse span:nth-child(4) { animation-delay: -1.05s; }
@keyframes orbit {
  from { transform: rotate(0deg) translateX(16px); }
  to   { transform: rotate(360deg) translateX(16px); }
}

.feedback-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.feedback-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}
.feedback-input {
  width: 100%;
  resize: vertical;
  background: var(--background-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 10px;
}
.feedback-input:focus { outline: 2px solid var(--accent-primary); outline-offset: 1px; }
.feedback-actions { display: flex; justify-content: flex-end; }

.modal-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.foot-right { display: flex; gap: 8px; }

.btn {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  padding: 8px 14px;
  border-radius: var(--radius-sm, 8px);
  cursor: pointer;
  border: 1px solid transparent;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: var(--accent-primary); color: #fff; }
.btn-primary:not(:disabled):hover { filter: brightness(1.05); }
.btn-secondary {
  background: var(--background-raised);
  color: var(--text-primary);
  border-color: var(--border-medium, var(--border-subtle));
}
.btn-secondary:not(:disabled):hover { background: var(--background-surface); }
.btn-ghost { background: none; color: var(--text-secondary); }
.btn-ghost:not(:disabled):hover { color: var(--text-primary); background: var(--background-raised); }
</style>
