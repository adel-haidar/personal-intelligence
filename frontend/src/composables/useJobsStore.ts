import { reactive, computed, type UnwrapNestedRefs } from 'vue'
import type { JobMatch, MatchTier, JobStatus, RunReport, SortField, SortDir, Country, PlatformsByCountry } from '../types/jobs'
import * as api from '../api/jobs'

const RUN_COUNTRIES_KEY = 'jobs.runCountries'
const RUN_PLATFORMS_KEY = 'jobs.runPlatforms'

function loadStoredList(key: string): string[] {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

function persistList(key: string, value: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch { /* ignore */ }
}

interface JobsState {
  matches: JobMatch[]
  totalCount: number
  isLoading: boolean
  isRunning: boolean
  runStatus: 'idle' | 'running' | 'done' | 'error'
  lastReport: RunReport | null
  lastRunAt: string | null
  error: string | null
  availableCountries: Country[]
  selectedRunCountries: string[]
  availablePlatforms: PlatformsByCountry
  selectedRunPlatforms: string[]
  platformsLoading: boolean
  platformsNeedKey: boolean
  filterTier: MatchTier | ''
  filterCountry: string
  filterStatus: JobStatus | ''
  filterPlatform: string
  sortField: SortField
  sortDir: SortDir
}

const state = reactive<JobsState>({
  matches: [],
  totalCount: 0,
  isLoading: false,
  isRunning: false,
  runStatus: 'idle',
  lastReport: null,
  lastRunAt: null,
  error: null,
  availableCountries: [],
  selectedRunCountries: loadStoredList(RUN_COUNTRIES_KEY),
  availablePlatforms: {},
  selectedRunPlatforms: loadStoredList(RUN_PLATFORMS_KEY),
  platformsLoading: false,
  platformsNeedKey: false,
  filterTier: '',
  filterCountry: '',
  filterStatus: '',
  filterPlatform: '',
  sortField: 'match_score',
  sortDir: 'desc',
})

const strongMatchCount = computed(() =>
  state.matches.filter(m => m.match_tier === 'STRONG_MATCH').length,
)

const appliedCount = computed(() =>
  state.matches.filter(m => m.status === 'applied' || m.status === 'interviewing').length,
)

const newCount = computed(() =>
  state.matches.filter(m => m.status === 'new').length,
)

const sortedMatches = computed((): JobMatch[] => {
  const arr = [...state.matches]
  const dir = state.sortDir === 'asc' ? 1 : -1
  return arr.sort((a, b) => {
    const av = a[state.sortField]
    const bv = b[state.sortField]
    if (av === bv) return 0
    if (av === null || av === undefined) return 1
    if (bv === null || bv === undefined) return -1
    return av < bv ? -dir : dir
  })
})

async function fetchMatches(): Promise<void> {
  state.isLoading = true
  state.error = null
  try {
    const res = await api.fetchMatches({
      tier:     state.filterTier     || undefined,
      country:  state.filterCountry  || undefined,
      status:   state.filterStatus   || undefined,
      platform: state.filterPlatform || undefined,
    })
    state.matches = res.matches
    state.totalCount = res.count
  } catch (err) {
    state.error = err instanceof Error ? err.message : 'Failed to fetch matches'
  } finally {
    state.isLoading = false
  }
}

async function loadCountries(): Promise<void> {
  if (state.availableCountries.length > 0) return
  try {
    const res = await api.fetchCountries()
    state.availableCountries = res.countries
  } catch {
    // non-fatal — the picker just shows nothing until a retry
  }
}

function toggleRunCountry(code: string): void {
  const i = state.selectedRunCountries.indexOf(code)
  if (i === -1) state.selectedRunCountries.push(code)
  else state.selectedRunCountries.splice(i, 1)
  persistList(RUN_COUNTRIES_KEY, state.selectedRunCountries)
  // The platform options depend on the chosen countries — refresh them.
  loadPlatforms()
}

const allPlatformKeys = computed((): Set<string> => {
  const keys = new Set<string>()
  for (const list of Object.values(state.availablePlatforms)) {
    for (const p of list) keys.add(p.platform_key)
  }
  return keys
})

async function loadPlatforms(): Promise<void> {
  const codes = state.selectedRunCountries
  if (codes.length === 0) {
    state.availablePlatforms = {}
    state.platformsNeedKey = false
    return
  }
  state.platformsLoading = true
  try {
    const res = await api.fetchPlatforms(codes)
    state.availablePlatforms = res.platforms
    state.platformsNeedKey = res.needs_key
    // Drop any selected platforms that no longer exist for the current countries.
    const valid = allPlatformKeys.value
    state.selectedRunPlatforms = state.selectedRunPlatforms.filter(k => valid.has(k))
    persistList(RUN_PLATFORMS_KEY, state.selectedRunPlatforms)
  } catch {
    // non-fatal — the picker just shows nothing until a retry
  } finally {
    state.platformsLoading = false
  }
}

function toggleRunPlatform(key: string): void {
  const i = state.selectedRunPlatforms.indexOf(key)
  if (i === -1) state.selectedRunPlatforms.push(key)
  else state.selectedRunPlatforms.splice(i, 1)
  persistList(RUN_PLATFORMS_KEY, state.selectedRunPlatforms)
}

async function openSetupGuide(): Promise<void> {
  try {
    await api.openSetupGuide()
  } catch (err) {
    state.error = err instanceof Error ? err.message : 'Failed to open setup guide'
  }
}

async function fetchReport(): Promise<void> {
  try {
    const report = await api.fetchReport()
    state.lastReport = report
    if (report.data?.timestamp) {
      state.lastRunAt = report.data.timestamp
    }
  } catch {
    // non-fatal — report may not exist yet
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null
let pollCount = 0
const MAX_POLLS = 360 // 30 minutes at 5-second intervals

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  pollCount = 0
}

async function triggerRun(): Promise<void> {
  if (state.isRunning) return
  if (state.selectedRunCountries.length === 0) {
    state.runStatus = 'error'
    state.error = 'Select at least one country before running the agent.'
    return
  }
  state.isRunning = true
  state.runStatus = 'running'
  state.error = null

  try {
    await api.triggerRun(state.selectedRunCountries, state.selectedRunPlatforms)
  } catch (err) {
    state.isRunning = false
    state.runStatus = 'error'
    state.error = err instanceof Error ? err.message : 'Failed to start run'
    return
  }

  stopPolling()

  pollTimer = setInterval(async () => {
    pollCount++

    if (pollCount > MAX_POLLS) {
      stopPolling()
      state.isRunning = false
      state.runStatus = 'error'
      state.error = 'Run timed out after 30 minutes — check server logs'
      return
    }

    try {
      const report = await api.fetchReport()
      state.lastReport = report
      if (report.data?.timestamp) state.lastRunAt = report.data.timestamp

      // Completion is driven by the run's persisted status, not by whether it
      // found NEW matches — a re-run that surfaces the same jobs saves 0 rows
      // but is still 'completed'. A killed/failed run reports its status too,
      // so we stop polling instead of waiting out the 30-min timeout.
      if (report.status === 'completed') {
        stopPolling()
        state.isRunning = false
        state.runStatus = 'done'
        await fetchMatches()
      } else if (report.status === 'failed' || report.status === 'interrupted') {
        stopPolling()
        state.isRunning = false
        state.runStatus = 'error'
        state.error = report.error || 'The job run did not finish — try again.'
      }
    } catch {
      // 404 before the first run row appears — keep polling.
    }
  }, 5000)
}

async function updateStatus(id: number, status: JobStatus): Promise<void> {
  await api.updateMatchStatus(id, status)
  const match = state.matches.find(m => m.id === id)
  if (match) match.status = status
}

function setFilter(field: 'tier' | 'country' | 'status' | 'platform', value: string): void {
  if (field === 'tier')     state.filterTier     = value as MatchTier | ''
  if (field === 'country')  state.filterCountry  = value
  if (field === 'status')   state.filterStatus   = value as JobStatus | ''
  if (field === 'platform') state.filterPlatform = value
  fetchMatches()
}

function clearFilters(): void {
  state.filterTier     = ''
  state.filterCountry  = ''
  state.filterStatus   = ''
  state.filterPlatform = ''
  fetchMatches()
}

function setSort(field: SortField): void {
  if (state.sortField === field) {
    state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc'
  } else {
    state.sortField = field
    state.sortDir   = 'desc'
  }
}

function clearError(): void {
  state.error = null
}

function dismissRunStatus(): void {
  if (state.runStatus === 'done' || state.runStatus === 'error') {
    state.runStatus = 'idle'
  }
}

const _store = reactive({
  state,
  strongMatchCount,
  appliedCount,
  newCount,
  sortedMatches,
  fetchMatches,
  fetchReport,
  loadCountries,
  toggleRunCountry,
  loadPlatforms,
  toggleRunPlatform,
  openSetupGuide,
  triggerRun,
  updateStatus,
  setFilter,
  clearFilters,
  setSort,
  clearError,
  dismissRunStatus,
})

type JobsStore = UnwrapNestedRefs<typeof _store>

export function useJobsStore(): JobsStore {
  return _store as unknown as JobsStore
}
