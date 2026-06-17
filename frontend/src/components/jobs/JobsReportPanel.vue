<script setup lang="ts">
import { ref, computed } from 'vue'
import { useJobsStore } from '../../composables/useJobsStore'

defineProps<{ expanded: boolean }>()
defineEmits<{ toggle: [] }>()

const store = useJobsStore()
const copied = ref(false)

const summaryLine = computed((): string => {
  const d = store.state.lastReport?.data
  if (!d) return ''
  return `${d.db_cumulative} total · ${d.strong_matches.length} strong · ${d.db_saved_this_run} this run`
})

async function copyReport(): Promise<void> {
  const text = store.state.lastReport?.report
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // clipboard not available
  }
}
</script>

<template>
  <div class="report-panel" :class="{ 'report-panel--expanded': expanded }">
    <button class="report-toggle" aria-label="Toggle report panel" @click="$emit('toggle')">
      <span class="report-toggle-label">Last run report</span>
      <span v-if="summaryLine" class="report-summary">{{ summaryLine }}</span>
      <span class="chevron" :class="{ 'chevron--up': expanded }">▾</span>
    </button>

    <div v-if="expanded" class="report-body">
      <div v-if="!store.state.lastReport" class="no-report">
        No report available — run the agent first.
      </div>
      <template v-else-if="store.state.lastReport.report">
        <div class="report-actions">
          <button class="btn btn-secondary copy-btn" @click="copyReport()">
            {{ copied ? 'Copied!' : 'Copy' }}
          </button>
        </div>
        <pre class="report-pre">{{ store.state.lastReport.report }}</pre>
      </template>
      <div v-else class="no-report">
        {{ store.state.lastReport.error
          || (store.state.lastReport.status === 'running'
            ? 'Run in progress…'
            : 'Run finished — open the matches list to see results.') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-panel {
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
  background: var(--background-surface);
}

.report-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}
.report-toggle:hover { background: var(--background-raised); }

.report-toggle-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.report-summary {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  flex: 1 1 auto;
}

.chevron {
  font-size: 14px;
  color: var(--text-tertiary);
  transition: transform 0.18s;
  flex-shrink: 0;
}
.chevron--up { transform: rotate(180deg); }

.report-body {
  padding: 0 16px 14px;
}

.no-report {
  font-size: 13px;
  color: var(--text-tertiary);
  padding: 12px 0;
}

.report-actions {
  display: flex;
  justify-content: flex-end;
  padding: 8px 0 6px;
}

.copy-btn {
  font-size: 12px;
  padding: 4px 12px;
}

.report-pre {
  background: var(--background-page);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  padding: 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  overflow-y: auto;
  max-height: 400px;
}
</style>
