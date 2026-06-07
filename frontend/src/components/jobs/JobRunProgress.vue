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
      dismissTimer = setTimeout(() => store.dismissRunStatus(), 5000)
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
          <span class="progress-text">
            Run complete — {{ doneMatchCount }} matches found.
            {{ doneStrongCount }} strong.
          </span>
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
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 10px 14px;
  margin: 10px 0;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-wrap--running { background: rgba(74,127,165,0.06); border-color: rgba(74,127,165,0.3); }
.progress-wrap--done    { background: rgba(58,122,90,0.08);  border-color: rgba(58,122,90,0.4); }
.progress-wrap--error   { background: rgba(122,58,58,0.08);  border-color: rgba(122,58,58,0.4); }

.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.progress-text { flex: 1 1 auto; color: var(--text-1); }

.elapsed {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.06em;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 1.5px solid rgba(74,127,165,0.3);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.icon-done  { color: var(--status-active); font-size: 14px; flex-shrink: 0; }
.icon-error { color: var(--status-error);  font-size: 14px; flex-shrink: 0; }

/* Indeterminate progress bar */
.progress-bar-track {
  height: 2px;
  background: var(--border);
  border-radius: 1px;
  overflow: hidden;
  position: relative;
}
.progress-bar-fill {
  position: absolute;
  top: 0;
  height: 100%;
  width: 40%;
  background: var(--accent);
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
  color: var(--text-3);
  cursor: pointer;
  font-size: 13px;
  padding: 0 4px;
  flex-shrink: 0;
}
.dismiss-btn:hover { color: var(--text-1); }

.retry-btn {
  font-size: 11px;
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
