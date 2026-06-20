<script setup lang="ts">
import { ref } from 'vue'
import type { JobMatch, JobStatus } from '../../types/jobs'
import { useJobsStore } from '../../composables/useJobsStore'
import ApplicationModal from './ApplicationModal.vue'

const props = defineProps<{ match: JobMatch }>()

const store = useJobsStore()
const showApplication = ref(false)

function onApplied(): void {
  // The backend already set the match to 'applied'; reflect it locally.
  props.match.status = 'applied'
}
const saving = ref(false)
const saveError = ref<string | null>(null)
let errorTimer: ReturnType<typeof setTimeout> | null = null

function scoreClass(score: number): string {
  if (score >= 70) return 'score--green'
  if (score >= 50) return 'score--amber'
  return 'score--red'
}

function remoteClass(type: string): string {
  const map: Record<string, string> = { remote: 'remote--green', hybrid: 'remote--blue', onsite: 'remote--gray' }
  return map[type] ?? 'remote--muted'
}

function rowClass(match: JobMatch): string {
  if (match.status === 'applied' || match.status === 'interviewing') return 'row--applied'
  if (match.status === 'rejected' || match.status === 'withdrawn')   return 'row--muted'
  if (match.match_tier === 'STRONG_MATCH')                           return 'row--strong'
  return ''
}

function platformLabel(p: string): string {
  const map: Record<string, string> = {
    'jobs.ch': 'jobs.ch',
    linkedin: 'LinkedIn',
    indeed: 'Indeed',
    stepstone: 'StepStone',
  }
  return map[p] ?? p
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' }).format(new Date(iso))
  } catch {
    return iso.slice(0, 10)
  }
}

async function onStatusChange(event: Event): Promise<void> {
  const select = event.target as HTMLSelectElement
  const newStatus = select.value as JobStatus
  const prevStatus = props.match.status
  if (newStatus === prevStatus) return

  saving.value = true
  saveError.value = null

  try {
    await store.updateStatus(props.match.id, newStatus)
  } catch (err) {
    select.value = prevStatus
    saveError.value = err instanceof Error ? err.message : 'Save failed'
    if (errorTimer) clearTimeout(errorTimer)
    errorTimer = setTimeout(() => { saveError.value = null }, 4000)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <tr :class="['match-row', rowClass(match)]">
    <!-- Score -->
    <td class="col-score">
      <span :class="['score-badge', scoreClass(match.match_score)]">{{ match.match_score }}</span>
    </td>

    <!-- Title -->
    <td class="col-title">
      <a :href="match.job_url" target="_blank" rel="noopener noreferrer" class="title-link">
        {{ match.title }}
      </a>
    </td>

    <!-- Company -->
    <td class="col-company">{{ match.company }}</td>

    <!-- Location -->
    <td class="col-location">{{ match.location }}, {{ match.country }}</td>

    <!-- Salary -->
    <td class="col-salary">{{ match.salary_raw ?? '—' }}</td>

    <!-- Remote -->
    <td class="col-remote">
      <span :class="['remote-pill', remoteClass(match.remote_type)]">{{ match.remote_type }}</span>
    </td>

    <!-- Platform -->
    <td class="col-platform">{{ platformLabel(match.platform) }}</td>

    <!-- Found date -->
    <td class="col-date">{{ formatDate(match.run_timestamp) }}</td>

    <!-- Status -->
    <td class="col-status">
      <div class="status-cell">
        <select
          :value="match.status"
          :disabled="saving"
          :aria-label="`Status for ${match.title} at ${match.company}`"
          :class="['status-select', `status--${match.status}`]"
          @change="onStatusChange"
        >
          <option value="new">New</option>
          <option value="reviewing">Reviewing</option>
          <option value="applied">Applied</option>
          <option value="interviewing">Interviewing</option>
          <option value="rejected">Rejected</option>
          <option value="withdrawn">Withdrawn</option>
          <option value="expired">Expired</option>
        </select>
        <span v-if="saving" class="saving-indicator">Saving…</span>
        <span v-if="saveError" class="save-error">{{ saveError }}</span>
      </div>
    </td>

    <!-- AI Summary -->
    <td class="col-summary">
      <span
        v-if="match.ai_summary"
        class="summary-text"
        :title="match.ai_summary"
      >{{ match.ai_summary }}</span>
      <span v-else class="no-summary">—</span>
    </td>

    <!-- Apply -->
    <td class="col-apply">
      <button
        class="apply-btn"
        :aria-label="`Generate an application for ${match.title} at ${match.company}`"
        @click="showApplication = true"
      >
        {{ match.status === 'applied' || match.status === 'interviewing' ? 'Review' : 'Apply' }}
      </button>
    </td>
  </tr>

  <ApplicationModal
    v-if="showApplication"
    :match="match"
    @close="showApplication = false"
    @applied="onApplied"
  />
</template>

<style scoped>
.match-row td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
  color: var(--text-primary);
  vertical-align: middle;
}
.match-row:last-child td { border-bottom: none; }
.match-row:hover td { background: var(--background-raised); }

/* Left-border accent */
.match-row.row--applied { border-left: 2px solid var(--accent-primary); }
.match-row.row--strong  { border-left: 2px solid var(--success); }
.match-row.row--muted td { opacity: 0.5; }

/* Score */
.score-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: var(--radius-sm, 8px);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
  min-width: 36px;
  text-align: center;
}
.score--green { background: var(--success-surface); color: var(--success); }
.score--amber { background: var(--warning-surface); color: var(--warning); }
.score--red   { background: var(--danger-surface);  color: var(--danger); }

/* Title */
.col-title { max-width: 260px; }
.title-link {
  color: var(--text-primary);
  text-decoration: none;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.title-link:hover { color: var(--accent-primary); }

/* Remote pill */
.remote-pill {
  display: inline-block;
  padding: 2px 7px;
  border-radius: var(--radius-pill, 999px);
  font-size: 11px;
  font-weight: 500;
}
.remote--green { background: var(--success-surface); color: var(--success); }
.remote--blue  { background: var(--accent-surface);  color: var(--accent-primary); }
.remote--gray  { background: var(--background-raised); color: var(--text-secondary); }
.remote--muted { color: var(--text-tertiary); }

/* Date */
.col-date {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

/* Status */
.status-cell { position: relative; display: inline-block; }
.status-select {
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 500;
  padding: 4px 8px;
  cursor: pointer;
  appearance: none;
  min-width: 110px;
}
.status-select:focus  { outline: 2px solid var(--accent-primary); outline-offset: 1px; }
.status-select:disabled { opacity: 0.5; cursor: not-allowed; }

.status--new          { color: var(--warning); }
.status--reviewing    { color: var(--accent-primary); }
.status--applied      { color: var(--success); }
.status--interviewing { color: var(--success); }
.status--rejected     { color: var(--danger); }
.status--withdrawn    { color: var(--text-tertiary); }
.status--expired      { color: var(--text-tertiary); }

.saving-indicator {
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  white-space: nowrap;
  margin-left: 6px;
}
.save-error {
  display: block;
  font-size: 10px;
  color: var(--danger);
  margin-top: 2px;
  font-family: var(--font-mono);
}

/* Apply */
.col-apply { white-space: nowrap; }
.apply-btn {
  background: var(--accent-primary);
  color: #fff;
  border: none;
  border-radius: var(--radius-sm, 8px);
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  cursor: pointer;
}
.apply-btn:hover { filter: brightness(1.06); }
.apply-btn:focus { outline: 2px solid var(--accent-primary); outline-offset: 1px; }

/* AI Summary */
.col-summary { max-width: 280px; }
.summary-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  cursor: default;
}
.no-summary { color: var(--text-tertiary); }
</style>
