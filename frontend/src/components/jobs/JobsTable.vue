<script setup lang="ts">
import { useJobsStore } from '../../composables/useJobsStore'
import type { SortField } from '../../types/jobs'
import JobsTableRow from './JobsTableRow.vue'

const store = useJobsStore()

interface ColDef {
  label: string
  field?: SortField
  sortable: boolean
}

const COLUMNS: ColDef[] = [
  { label: 'Score',      field: 'match_score',    sortable: true  },
  { label: 'Title',                               sortable: false },
  { label: 'Company',    field: 'company',         sortable: true  },
  { label: 'Location',   field: 'country',         sortable: true  },
  { label: 'Salary',                              sortable: false },
  { label: 'Remote',                              sortable: false },
  { label: 'Platform',                            sortable: false },
  { label: 'Found',      field: 'run_timestamp',  sortable: true  },
  { label: 'Status',                              sortable: false },
  { label: 'AI summary',                          sortable: false },
  { label: 'Apply',                               sortable: false },
]

function headerClass(col: ColDef): Record<string, boolean> {
  return {
    sortable: col.sortable,
    'sort-active': col.sortable && col.field === store.state.sortField,
  }
}

function sortIndicator(col: ColDef): string {
  if (!col.sortable || col.field !== store.state.sortField) return ''
  return store.state.sortDir === 'asc' ? ' ▲' : ' ▼'
}

function onHeaderClick(col: ColDef): void {
  if (col.sortable && col.field) store.setSort(col.field)
}
</script>

<template>
  <div class="table-container">
    <!-- Skeleton loading state -->
    <table v-if="store.state.isLoading" class="jobs-table" aria-busy="true" aria-label="Loading matches">
      <thead>
        <tr>
          <th v-for="col in COLUMNS" :key="col.label" scope="col">{{ col.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="i in 5" :key="i" class="skeleton-row">
          <td v-for="j in COLUMNS.length" :key="j">
            <div :class="['skel', j === 2 || j === 10 ? 'skel-lg' : j % 2 === 0 ? 'skel-md' : 'skel-sm']"></div>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Empty state -->
    <div v-else-if="store.sortedMatches.length === 0" class="empty-state">
      <p class="empty-msg">No matches yet — run the agent to start searching.</p>
      <button class="btn btn-secondary empty-run-btn" @click="store.triggerRun()">
        Run agent →
      </button>
    </div>

    <!-- Data table -->
    <table v-else class="jobs-table" aria-label="Job matches">
      <thead>
        <tr>
          <th
            v-for="col in COLUMNS"
            :key="col.label"
            scope="col"
            :class="headerClass(col)"
            @click="onHeaderClick(col)"
          >
            {{ col.label }}{{ sortIndicator(col) }}
          </th>
        </tr>
      </thead>
      <tbody>
        <JobsTableRow
          v-for="match in store.sortedMatches"
          :key="match.id"
          :match="match"
        />
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.table-container {
  width: 100%;
}

.jobs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.jobs-table thead tr {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--background-raised);
}

.jobs-table th {
  padding: 9px 12px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
  user-select: none;
}

.sortable {
  cursor: pointer;
  transition: color 0.12s;
}
.sortable:hover { color: var(--text-primary); }
.sort-active { color: var(--accent-primary); }

/* Skeleton rows */
.skeleton-row td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
}
.skel {
  height: 13px;
  border-radius: var(--radius-sm, 8px);
  background: var(--background-raised);
  animation: pulse 1.4s ease-in-out infinite;
}
.skel-sm { width: 48px; }
.skel-md { width: 100px; }
.skel-lg { width: 190px; }
@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50%       { opacity: 0.9; }
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 64px 32px;
  min-height: 200px;
}
.empty-msg {
  font-size: 14px;
  color: var(--text-secondary);
  text-align: center;
}
.empty-run-btn { font-size: 13px; }
</style>
