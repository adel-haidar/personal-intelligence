<script setup lang="ts">
import { ref, watch, onUnmounted, computed } from 'vue'
import { useJobsStore } from '../../composables/useJobsStore'

const store = useJobsStore()

const PHASES = ['Searching platforms…', 'Scoring matches…', 'Saving to database…']
const phaseIndex = ref(0)
const elapsedSecs = ref(0)
const doneMatchCount = ref(0)
const doneStrongCount = ref(0)

let phaseTimer: ReturnType<typeof setInterval> | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null
let dismissTimer: ReturnType<typeof setTimeout> | null = null

const visible = computed(() => store.state.runStatus !== 'idle')
// A completed run with nothing to show carries a reason (empty scrape, quota,
// no profile). Surface it instead of a bare "0 matches found".
const runNotice = computed(() => store.state.lastReport?.data?.notice ?? null)

watch(() => store.state.runStatus, (status) => {
  if (status === 'running') {
    phaseIndex.value = 0
    elapsedSecs.value = 0

    phaseTimer = setInterval(() => {
      phaseIndex.value = (phaseIndex.value + 1) % PHASES.length
    }, 5000)

    elapsedTimer = setInterval(() => {
      elapsedSecs.value++
    }, 1000)
  } else {
    if (phaseTimer)   { clearInterval(phaseTimer);  phaseTimer   = null }
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }

    if (status === 'done') {
      doneMatchCount.value  = store.state.matches.length
      doneStrongCount.value = store.strongMatchCount
      // Keep an explanatory notice on screen; only auto-dismiss the plain
      // "run complete" confirmation.
      if (!runNotice.value) {
        dismissTimer = setTimeout(() => store.dismissRunStatus(), 5000)
      }
    }
  }
})

onUnmounted(() => {
  if (phaseTimer)   clearInterval(phaseTimer)
  if (elapsedTimer) clearInterval(elapsedTimer)
  if (dismissTimer) clearTimeout(dismissTimer)
})
</script>

<template>
  <Transition name="progress-fade">
    <div v-if="visible" class="progress-wrap" :class="`progress-wrap--${store.state.runStatus}`">

      <!-- Running state -->
      <template v-if="store.state.runStatus === 'running'">
        <div class="progress-row">
          <span class="spinner" aria-hidden="true"></span>
          <span class="progress-text">{{ PHASES[phaseIndex] }}</span>
          <span class="elapsed">{{ elapsedSecs }}s</span>
        </div>
        <div class="progress-bar-track" role="progressbar" aria-label="Agent running">
          <div class="progress-bar-fill"></div>
        </div>
      </template>

      <!-- Done state -->
      <template v-else-if="store.state.runStatus === 'done'">
        <div class="progress-row">
          <span class="icon-done" aria-hidden="true">✓</span>
          <span v-if="runNotice" class="progress-text">{{ runNotice }}</span>
          <span v-else class="progress-text">
            Run complete — {{ doneMatchCount }} matches found.
            {{ doneStrongCount }} strong.
          </span>
          <button
            v-if="runNotice"
            class="btn btn-secondary retry-btn"
            @click="store.triggerRun()"
          >Retry</button>
          <button class="dismiss-btn" aria-label="Dismiss" @click="store.dismissRunStatus()">✕</button>
        </div>
      </template>

      <!-- Error state -->
      <template v-else-if="store.state.runStatus === 'error'">
        <div class="progress-row">
          <span class="icon-error" aria-hidden="true">✗</span>
          <span class="progress-text">{{ store.state.error ?? 'Run failed' }}</span>
          <button class="btn btn-secondary retry-btn" @click="store.triggerRun()">Retry</button>
          <button class="dismiss-btn" aria-label="Dismiss" @click="store.dismissRunStatus()">✕</button>
        </div>
      </template>

    </div>
  </Transition>
</template>

<style scoped>
.progress-wrap {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  padding: 10px 14px;
  margin: 10px 0;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-wrap--running {
  background: var(--accent-surface);
  border-color: var(--accent-primary);
}
.progress-wrap--done {
  background: var(--success-surface);
  border-color: var(--success);
}
.progress-wrap--error {
  background: var(--danger-surface);
  border-color: var(--danger);
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.progress-text { flex: 1 1 auto; color: var(--text-primary); }

.elapsed {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
}

.spinner {
  width: 14px;
  height: 14px;
  border: 1.5px solid var(--border-medium);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.icon-done  { color: var(--success); font-size: 14px; flex-shrink: 0; }
.icon-error { color: var(--danger);  font-size: 14px; flex-shrink: 0; }

/* Indeterminate progress bar */
.progress-bar-track {
  height: 2px;
  background: var(--border-subtle);
  border-radius: 1px;
  overflow: hidden;
  position: relative;
}
.progress-bar-fill {
  position: absolute;
  top: 0;
  height: 100%;
  width: 40%;
  background: var(--accent-primary);
  border-radius: 1px;
  animation: slide 1.8s ease-in-out infinite;
}
@keyframes slide {
  0%   { left: -40%; }
  100% { left: 100%; }
}

.dismiss-btn {
  background: none;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 13px;
  padding: 0 4px;
  flex-shrink: 0;
}
.dismiss-btn:hover { color: var(--text-primary); }

.retry-btn {
  font-size: 12px;
  padding: 4px 10px;
  flex-shrink: 0;
}

/* Transition */
.progress-fade-enter-active, .progress-fade-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.progress-fade-enter-from, .progress-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (prefers-reduced-motion: reduce) {
  .spinner, .progress-bar-fill { animation: none; }
  .progress-fade-enter-active, .progress-fade-leave-active { transition: none; }
}
</style>
