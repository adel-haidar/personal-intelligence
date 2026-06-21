<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useJobsStore } from '../composables/useJobsStore'
import PageHead from '../components/ui/PageHead.vue'
import JobsStats from '../components/jobs/JobsStats.vue'
import JobsFilters from '../components/jobs/JobsFilters.vue'
import JobsCountryPicker from '../components/jobs/JobsCountryPicker.vue'
import JobsPlatformPicker from '../components/jobs/JobsPlatformPicker.vue'
import JobsTable from '../components/jobs/JobsTable.vue'
import JobRunProgress from '../components/jobs/JobRunProgress.vue'
import JobsReportPanel from '../components/jobs/JobsReportPanel.vue'

const store = useJobsStore()
const showReport = ref(false)

onMounted(async () => {
  await Promise.all([store.fetchMatches(), store.fetchReport(), store.loadCountries()])
  // Populate the platform picker for any countries restored from a prior session.
  if (store.state.selectedRunCountries.length > 0) await store.loadPlatforms()
})
</script>

<template>
  <div class="jobs-view">
    <div v-if="store.state.error" class="error-banner">
      <span>{{ store.state.error }}</span>
      <button class="error-dismiss" aria-label="Dismiss error" @click="store.clearError()">✕</button>
    </div>

    <div class="jobs-header">
      <div class="header-left">
        <PageHead
          title="Job hunt"
          desc="AI-scored matches — pick countries, then the best boards for each"
        />
      </div>
      <div class="header-right">
        <div class="btn-group">
          <JobsCountryPicker />
          <JobsPlatformPicker />
          <button
            class="btn btn-secondary"
            :aria-pressed="showReport"
            @click="showReport = !showReport"
          >
            {{ showReport ? 'Hide report' : 'View report' }}
          </button>
          <button
            class="btn btn-primary run-btn"
            :disabled="store.state.isRunning || store.state.selectedRunCountries.length === 0"
            :title="store.state.selectedRunCountries.length === 0 ? 'Select at least one country first' : 'Run job hunt agent'"
            aria-label="Run job hunt agent"
            @click="store.triggerRun()"
          >
            <span v-if="store.state.isRunning" class="spinner" aria-hidden="true"></span>
            {{ store.state.isRunning ? 'Running…' : 'Run agent' }}
          </button>
        </div>
        <p class="last-run-text">{{ store.state.lastRunAt ? `Last run: ${new Date(store.state.lastRunAt).toLocaleString()}` : 'Never run' }}</p>
      </div>
    </div>

    <JobsStats />
    <JobsFilters />
    <JobRunProgress />

    <div class="table-wrap">
      <JobsTable />
    </div>

    <JobsReportPanel :expanded="showReport" @toggle="showReport = !showReport" />
  </div>
</template>

<style scoped>
.jobs-view {
  display: flex;
  flex-direction: column;
  height: calc(100svh - var(--header-h) - var(--gutter) * 2);
  min-height: 0;
  gap: 0;
}

.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  margin-bottom: 12px;
  background: var(--danger-surface);
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm, 8px);
  font-size: 13px;
  color: var(--danger);
  flex-shrink: 0;
}

.error-dismiss {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
  opacity: 0.7;
  flex-shrink: 0;
}
.error-dismiss:hover { opacity: 1; }

/* Header row — PageHead on left, actions on right */
.jobs-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  flex-shrink: 0;
}

.header-left {
  flex: 1 1 auto;
  min-width: 0;
}

.header-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
  padding-top: 4px;
}

.btn-group {
  display: flex;
  gap: 8px;
}

.run-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 110px;
  justify-content: center;
}
.run-btn:disabled { opacity: 0.7; cursor: not-allowed; }

.spinner {
  width: 12px;
  height: 12px;
  border: 1.5px solid var(--border-medium);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.last-run-text {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.table-wrap {
  flex: 1 1 auto;
  overflow-y: auto;
  min-height: 0;
  border-top: 1px solid var(--border-subtle);
  border-bottom: 1px solid var(--border-subtle);
}
</style>
