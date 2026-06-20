<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount, onMounted } from 'vue'
import {
  Chart,
  LineElement, PointElement, LineController,
  BarElement, BarController,
  CategoryScale, LinearScale,
  Tooltip,
  type ChartConfiguration,
} from 'chart.js'
import PageHead from '../components/ui/PageHead.vue'
import PiCard from '../components/ui/PiCard.vue'
import PIIcon from '../components/ui/PIIcon.vue'
import PiButton from '../components/ui/PiButton.vue'
import UploadBanner from '../components/ui/UploadBanner.vue'
import StatusPill from '../components/ui/StatusPill.vue'
import InsightCard from '../components/ui/InsightCard.vue'
import InsightLine from '../components/ui/InsightLine.vue'
import DeviceCard from '../components/ui/DeviceCard.vue'
import ConfirmModal from '../components/ui/ConfirmModal.vue'
import ShareButton from '../components/ui/ShareButton.vue'
import HealthExportGuide from '../components/health/HealthExportGuide.vue'
import GoalPrompt from '../components/GoalPrompt.vue'
import { useHealthDaily, useHealthTrends, useAppleHealthImport, useSamsungHealthImport, useHealthStatus } from '../composables/useHealth'
import { requireAuth } from '../composables/useAuth'
import { API_BASE } from '../config/env'
import { useToast } from '../components/ui/useToast'
import { useI18n } from '../i18n/index'
import { checkWeightGoal, saveWeightGoal, useWeightGoal } from '../composables/useGoal'
import type { User } from '../types/user'

Chart.register(
  LineElement, PointElement, LineController,
  BarElement, BarController,
  CategoryScale, LinearScale,
  Tooltip,
)

// ── Composables ─────────────────────────────────────────────────────────────
const { status: dailyStatus, result: daily, error: dailyError, fetchDaily, runDaily } = useHealthDaily()
const { trends, error: trendError, status: trendStatus, fetchTrends } = useHealthTrends()
const { status: importStatus, error: importError, uploadFile } = useAppleHealthImport()
const { status: samsungImportStatus, error: samsungImportError, uploadFile: uploadSamsungFile } = useSamsungHealthImport()
const { data: healthStatus, fetchStatus } = useHealthStatus()
const toast = useToast()
const { t } = useI18n()
const { weightGoal } = useWeightGoal()

// ── Goal prompt ───────────────────────────────────────────────────────────────
const goalPromptOpen = ref(false)
const goalSaving = ref(false)
const goalError = ref('')

async function onSaveWeightGoal(payload: { kg?: number }) {
  if (!payload.kg) return
  goalSaving.value = true
  goalError.value = ''
  try {
    await saveWeightGoal(payload.kg)
    goalPromptOpen.value = false
    // Rebuild chart to include the new goal line
    if (chartsOpen.value) nextTick(buildCharts)
  } catch {
    goalError.value = 'Could not save your goal — please try again.'
  } finally {
    goalSaving.value = false
  }
}

const today = new Date().toISOString().slice(0, 10)
// The date we currently show analysis for — moves to the latest imported day.
const activeDate = ref(today)
const trendDays = ref(30)

// ── Data presence ─────────────────────────────────────────────────────────────
const hasAnalysis = computed(() => !!(daily.value && daily.value.status !== 'not_run'))
const hasTrendData = computed(() =>
  !!trends.value && Object.values(trends.value.series).some(s => s.length > 0),
)
// Persistent, all-time signal: the brain already holds data for this user. Keeps
// the page out of the empty first-run state on every login even after the newest
// synced data ages out of the trend window.
const hasBrainData = computed(() => !!healthStatus.value?.latest_data_date)
const hasData = computed(() => hasAnalysis.value || hasTrendData.value || hasBrainData.value)

const latestTrendDate = computed(() => {
  if (!trends.value) return null
  let max: string | null = null
  for (const series of Object.values(trends.value.series)) {
    for (const p of series) if (!max || p.date > max) max = p.date
  }
  return max
})

// ── Apple Health upload ────────────────────────────────────────────────────────
const ahInput = ref<HTMLInputElement | null>(null)
function pickFile() { ahInput.value?.click() }

async function onPickFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await doUpload(file)
}

async function doUpload(file: File) {
  try {
    const r = await uploadFile(file)
    toast(`Imported ${r.inserted} records (${r.date_range[0]} → ${r.date_range[1]})`, 'success')
    addDeviceOpen.value = false
    // Run the analysis for the most recent imported day so insights appear.
    const target = r.date_range[1] || today
    activeDate.value = target
    await fetchStatus()
    await fetchTrends(trendDays.value, target)
    await runDaily(target)
  } catch {
    toast(importError.value ?? 'Upload failed', 'error')
  }
}

async function updateAnalysis() {
  const target = latestTrendDate.value || activeDate.value
  activeDate.value = target
  await runDaily(target)
  if (dailyStatus.value === 'error') toast(dailyError.value ?? 'Analysis failed', 'error')
}

// ── Export guide ────────────────────────────────────────────────────────────────
const guideOpen = ref(false)
const guidePlatform = ref<'ios' | 'android'>('ios')
function openGuide(platform: 'ios' | 'android') {
  guidePlatform.value = platform
  guideOpen.value = true
}

// ── Devices ─────────────────────────────────────────────────────────────────────
const addDeviceOpen = ref(false)

function statusSource(source: 'apple_watch' | 'beurer_scale' | 'samsung_health') {
  return healthStatus.value?.sources.find(s => s.source === source)
}

// Apple sync state must come from Apple-attributed signals ONLY. Trends
// (hasTrendData / latestTrendDate) aggregate across every source, so falling
// back to them lit up the Apple Watch card — with the wrong date — whenever any
// other device (e.g. a Samsung export) had data. # see bug: phantom apple sync
const appleSynced = computed(() => {
  if (statusSource('apple_watch')?.has_data) return true
  const avail = (daily.value?.data_availability ?? []).find(a => a.source === 'apple_watch')
  return !!(avail?.available || avail?.last_data_date)
})
const appleLastSync = computed(() => {
  const avail = (daily.value?.data_availability ?? []).find(a => a.source === 'apple_watch')
  return statusSource('apple_watch')?.last_data_date ?? avail?.last_data_date ?? undefined
})
const scaleSynced = computed(() => !!statusSource('beurer_scale')?.has_data)
const scaleLastSync = computed(() => statusSource('beurer_scale')?.last_data_date ?? undefined)
const samsungSynced = computed(() => !!statusSource('samsung_health')?.has_data)
const samsungLastSync = computed(() => statusSource('samsung_health')?.last_data_date ?? undefined)

interface DeviceDef {
  icon: string; name: string; appleHealth: boolean
  acceptHint: string; instructions: string[]
  synced: boolean; lastSync?: string
}
const allDevices = computed<DeviceDef[]>(() => [
  {
    icon: 'watch', name: 'Apple Watch', appleHealth: true,
    acceptHint: 'Accepts the .zip export from the Health app',
    instructions: ['Open the Health app on iPhone', 'Tap your profile photo, then Export All Health Data', 'Upload the generated export.zip here'],
    synced: appleSynced.value, lastSync: appleLastSync.value,
  },
  {
    icon: 'watch', name: 'Samsung Health', appleHealth: false,
    acceptHint: 'Accepts .json / .zip',
    instructions: ['Open Samsung Health', 'Settings → Download personal data', 'Upload the archive here'],
    synced: samsungSynced.value, lastSync: samsungLastSync.value,
  },
  {
    icon: 'device', name: 'Garmin', appleHealth: false,
    acceptHint: 'Accepts .fit / .zip',
    instructions: ['Sign in to Garmin Connect on the web', 'Account → Export Your Data', 'Upload the archive here'],
    synced: false,
  },
  {
    icon: 'scale', name: 'Smart Scale', appleHealth: false,
    acceptHint: 'Accepts .csv',
    instructions: ['Open your scale’s companion app', 'Export weight history as CSV', 'Upload the file here'],
    synced: scaleSynced.value, lastSync: scaleLastSync.value,
  },
])
const syncedDevices = computed(() => allDevices.value.filter(d => d.synced))

async function doSamsungUpload(file: File) {
  try {
    const r = await uploadSamsungFile(file)
    toast(`Imported ${r.inserted} records (${r.date_range[0]} → ${r.date_range[1]})`, 'success')
    addDeviceOpen.value = false
    const target = r.date_range[1] || today
    activeDate.value = target
    await fetchStatus()
    await fetchTrends(trendDays.value, target)
    await runDaily(target)
  } catch {
    toast(samsungImportError.value ?? 'Upload failed', 'error')
  }
}

async function onDeviceFiles(device: DeviceDef, files: File[]) {
  const file = files[0]
  if (!file) return
  if (device.appleHealth) {
    await doUpload(file)
    return
  }
  if (device.name === 'Samsung Health') {
    await doSamsungUpload(file)
    return
  }
  // Generic fallback for unsupported devices — store raw file in brain memory
  try {
    const token = await requireAuth()
    const fd = new FormData()
    fd.append('files', file)
    const res = await fetch(`${API_BASE}/api/file`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd })
    toast(res.ok ? 'File added to your brain' : 'Upload failed', res.ok ? 'success' : 'error')
    if (res.ok) addDeviceOpen.value = false
  } catch {
    toast('Upload failed', 'error')
  }
}

// ── Formatting ────────────────────────────────────────────────────────────────
function fmtKg(v: number | null | undefined): string { return v != null ? `${v.toFixed(1)} kg` : '—' }
function fmtBpm(v: number | null | undefined): string { return v != null ? `${v.toFixed(0)} bpm` : '—' }
function fmtSteps(v: number | null | undefined): string { return v != null ? v.toLocaleString() : '—' }
function fmtSleep(v: number | null | undefined): string {
  if (v == null) return '—'
  const h = Math.floor(v / 60); const m = Math.round(v % 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

const statRow = computed(() => {
  const s = daily.value?.summary
  return [
    { label: 'Steps', value: fmtSteps(s?.steps) },
    { label: 'Resting heart rate', value: fmtBpm(s?.resting_hr) },
    { label: 'Sleep', value: fmtSleep(s?.sleep_duration_min) },
    { label: 'Weight', value: fmtKg(s?.weight_kg) },
  ]
})

const trend = computed(() => daily.value?.summary.weight_trend_kg_per_week ?? null)
const flags = computed(() => daily.value?.flags ?? [])
const glanceStatus = computed<{ kind: 'good' | 'watch' | 'attention'; text: string }>(() => {
  if (flags.value.includes('goal_reached')) return { kind: 'good', text: 'Goal reached' }
  if (flags.value.includes('weight_loss_too_fast')) return { kind: 'attention', text: 'Losing too fast' }
  if (trend.value != null && trend.value < 0) return { kind: 'good', text: 'On track' }
  return { kind: 'watch', text: 'Steady' }
})
function fmtTrend(v: number | null): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(1)} kg/wk`
}
const trendIcon = computed(() => (trend.value != null && trend.value < 0 ? 'down' : 'arrowRight'))
const trendColor = computed(() => {
  if (trend.value == null) return 'var(--text-secondary)'
  if (trend.value < 0) return 'var(--success)'
  if (trend.value > 0) return 'var(--warning)'
  return 'var(--text-secondary)'
})

const showNumbers = ref(false)
interface Line { kind: 'good' | 'watch' | 'attention' | 'info'; label: string; text: string; raw?: string }
const numberLines = computed<Line[]>(() => {
  const s = daily.value?.summary
  const out: Line[] = []
  for (const f of flags.value) {
    switch (f) {
      case 'low_hrv_3_days':
        out.push({ kind: 'watch', label: 'Watch', text: 'Your heart-rate variability has been low for several days, which can signal fatigue or stress. Lighter training and earlier nights help.', raw: s?.hrv_ms != null ? `HRV ${s.hrv_ms} ms` : undefined }); break
      case 'sleep_below_target':
        out.push({ kind: 'watch', label: 'Watch', text: "You've been sleeping below your target. Recovery happens during sleep — aim for an earlier, more consistent bedtime.", raw: s?.sleep_duration_min != null ? `Sleep ${fmtSleep(s.sleep_duration_min)}` : undefined }); break
      case 'resting_hr_elevated':
        out.push({ kind: 'watch', label: 'Watch', text: 'Your resting heart rate is higher than usual, which often follows poor sleep or added stress.', raw: s?.resting_hr != null ? `Resting HR ${s.resting_hr.toFixed(0)} bpm` : undefined }); break
      case 'weight_loss_too_fast':
        out.push({ kind: 'attention', label: 'Attention', text: "You're losing weight quite fast. Rapid loss is hard to sustain and can cost muscle — consider easing the deficit.", raw: `Trend ${fmtTrend(trend.value)}` }); break
      case 'weight_plateau':
        out.push({ kind: 'info', label: 'Steady', text: "Your weight has been steady recently. If you're aiming to change it, small consistent adjustments work best.", raw: s?.weight_kg != null ? `Weight ${fmtKg(s.weight_kg)}` : undefined }); break
      case 'goal_reached':
        out.push({ kind: 'good', label: 'Healthy', text: "You've reached your weight goal. The focus now shifts to maintaining it.", raw: s?.weight_kg != null ? `Weight ${fmtKg(s.weight_kg)}` : undefined }); break
      default:
        out.push({ kind: 'info', label: 'Note', text: f.replace(/_/g, ' ') })
    }
  }
  if (out.length === 0) out.push({ kind: 'good', label: 'Healthy', text: 'Your recent metrics are within a healthy range. Keep up your current habits.' })
  return out
})

const dataSuggests = computed(() => daily.value?.analysis || daily.value?.coach_insight || daily.value?.reasoning || '')

// Privacy-preserving share card: a qualitative headline derived from the glance
// status — never raw weight / heart-rate / sleep numbers.
const healthHighlight = computed(() => {
  const map: Record<string, string> = {
    'Goal reached': 'I reached my health goal 🎯',
    'On track': 'Staying on track with my health 💪',
    'Steady': 'Keeping my health steady 🌿',
    'Losing too fast': 'Fine-tuning my health plan 🔄',
  }
  return {
    headline: map[glanceStatus.value.text] ?? 'My health check-in',
    caption: 'Tracked privately with my own AI brain',
  }
})

// ── Detailed charts (collapsed) ──────────────────────────────────────────────
const chartsOpen = ref(false)
const chartWeightRef = ref<HTMLCanvasElement | null>(null)
const chartHrRef = ref<HTMLCanvasElement | null>(null)
const chartHrvRef = ref<HTMLCanvasElement | null>(null)
const chartSleepRef = ref<HTMLCanvasElement | null>(null)
const chartStepsRef = ref<HTMLCanvasElement | null>(null)
let chartWeight: Chart | null = null
let chartHr: Chart | null = null
let chartHrv: Chart | null = null
let chartSleep: Chart | null = null
let chartSteps: Chart | null = null

function cssVar(name: string): string { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() }
function tooltipDefaults() {
  return {
    backgroundColor: cssVar('--background-raised'), titleColor: cssVar('--text-primary'),
    bodyColor: cssVar('--text-secondary'), borderColor: cssVar('--border-subtle'), borderWidth: 1,
    titleFont: { family: cssVar('--font-mono'), size: 11 }, bodyFont: { family: cssVar('--font-mono'), size: 11 },
  }
}
function makeScales(yLabel?: string) {
  const border = cssVar('--border-subtle'); const text2 = cssVar('--text-secondary')
  return {
    x: { grid: { color: `${border}60`, borderColor: 'transparent' }, ticks: { color: text2, font: { family: cssVar('--font-mono'), size: 10 }, maxRotation: 0, maxTicksLimit: 8 } },
    y: { grid: { color: `${border}60`, borderColor: 'transparent' }, ticks: { color: text2, font: { family: cssVar('--font-mono'), size: 10 } }, title: yLabel ? { display: true, text: yLabel, color: text2, font: { family: cssVar('--font-mono'), size: 9 } } : undefined },
  }
}
const BASE_OPTS = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
function destroyCharts() {
  chartWeight?.destroy(); chartWeight = null; chartHr?.destroy(); chartHr = null
  chartHrv?.destroy(); chartHrv = null; chartSleep?.destroy(); chartSleep = null
  chartSteps?.destroy(); chartSteps = null
}
function buildCharts() {
  destroyCharts()
  if (!trends.value) return
  const series = trends.value.series
  const accent = cssVar('--accent-primary') || '#5B5BD6'
  const amber = cssVar('--brain-amber') || '#E8A444'
  const success = cssVar('--success') || '#2D7A4F'
  const danger = cssVar('--danger') || '#C0392B'

  if (chartWeightRef.value) {
    const wData = series['weight_kg'] ?? []
    const labels = wData.map(p => p.date.slice(5))
    const weights = wData.map(p => p.value)
    const avg7: (number | null)[] = weights.map((_, i) => { if (i < 6) return null; const sl = weights.slice(i - 6, i + 1); return sl.reduce((s, v) => s + v, 0) / sl.length })
    const goalKg = weightGoal.value
    const weightDatasets: ChartConfiguration<'line'>['data']['datasets'] = [
      { label: 'Weight', data: weights, borderColor: accent, borderWidth: 1.5, pointRadius: 2, pointBackgroundColor: accent, fill: false, tension: 0.3, spanGaps: true },
      { label: '7-day avg', data: avg7, borderColor: amber, borderWidth: 2, pointRadius: 0, fill: false, tension: 0.4, spanGaps: true },
    ]
    if (goalKg !== null) {
      weightDatasets.push({ label: `Goal ${goalKg} kg`, data: labels.map(() => goalKg), borderColor: success, borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, fill: false } as any)
    }
    chartWeight = new Chart(chartWeightRef.value, { type: 'line', data: { labels, datasets: weightDatasets }, options: { ...BASE_OPTS, scales: makeScales('kg'), plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (c) => ` ${c.dataset.label}: ${typeof c.parsed.y === 'number' ? c.parsed.y.toFixed(1) : '—'} kg` } } } } } as ChartConfiguration<'line'>)
  }
  if (chartHrRef.value) {
    const d = (series['resting_hr'] ?? []).slice(-14)
    chartHr = new Chart(chartHrRef.value, { type: 'line', data: { labels: d.map(p => p.date.slice(5)), datasets: [{ data: d.map(p => p.value), borderColor: amber, borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.35, spanGaps: true }] }, options: { ...BASE_OPTS, scales: makeScales('bpm'), plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (c) => ` ${c.parsed.y} bpm` } } } } } as ChartConfiguration<'line'>)
  }
  if (chartHrvRef.value) {
    const d = (series['hrv_ms'] ?? []).slice(-14)
    chartHrv = new Chart(chartHrvRef.value, { type: 'line', data: { labels: d.map(p => p.date.slice(5)), datasets: [{ data: d.map(p => p.value), borderColor: success, borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.35, spanGaps: true }] }, options: { ...BASE_OPTS, scales: makeScales('ms'), plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (c) => ` ${c.parsed.y} ms` } } } } } as ChartConfiguration<'line'>)
  }
  if (chartSleepRef.value) {
    const d = (series['sleep_duration_min'] ?? []).slice(-7)
    const values = d.map(p => +(p.value / 60).toFixed(2))
    chartSleep = new Chart(chartSleepRef.value, { type: 'bar', data: { labels: d.map(p => p.date.slice(5)), datasets: [
      { label: 'Sleep (h)', data: values, backgroundColor: values.map(v => v >= 7 ? success : danger), borderWidth: 0 } as any,
      { label: 'Target', data: values.map(() => 8), type: 'line', borderColor: amber, borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, fill: false } as any,
    ] }, options: { ...BASE_OPTS, scales: { ...makeScales('h'), y: { ...makeScales('h').y, min: 0, max: 10 } }, plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (c: any) => ` ${c.parsed.y} h` } } } } } as ChartConfiguration)
  }
  if (chartStepsRef.value) {
    const d = (series['steps'] ?? []).slice(-7)
    chartSteps = new Chart(chartStepsRef.value, { type: 'bar', data: { labels: d.map(p => p.date.slice(5)), datasets: [{ label: 'Steps', data: d.map(p => p.value), backgroundColor: accent, borderWidth: 0 }] }, options: { ...BASE_OPTS, scales: makeScales('steps'), plugins: { legend: { display: false }, tooltip: { ...tooltipDefaults(), callbacks: { label: (c) => ` ${c.parsed.y?.toLocaleString() ?? 0} steps` } } } } } as ChartConfiguration<'bar'>)
  }
}
watch(chartsOpen, (open) => { if (open) nextTick(buildCharts); else destroyCharts() })
watch(trends, () => { if (chartsOpen.value) nextTick(buildCharts) })
watch(trendDays, (d) => fetchTrends(d, activeDate.value))
onBeforeUnmount(destroyCharts)

// ── Delete all health data ───────────────────────────────────────────────────
const confirmDel = ref(false)
async function deleteAll() {
  confirmDel.value = false
  try {
    const token = await requireAuth()
    const res = await fetch(`${API_BASE}/api/health/data`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) { toast('Health data deleted', 'warning'); fetchStatus(); fetchDaily(activeDate.value); fetchTrends(trendDays.value, activeDate.value) }
    else toast('Deleting health data isn’t available yet.', 'error')
  } catch { toast('Deleting health data isn’t available yet.', 'error') }
}

// ── Send analysis to doctor ──────────────────────────────────────────────────
const sendingToDoctor = ref(false)

/** UTF-8-safe btoa: encodes a JS string (any Unicode) to base64. */
function utf8ToBase64(str: string): string {
  return btoa(unescape(encodeURIComponent(str)))
}

/** Wrap a flat base64 string into 76-char CRLF-terminated lines (RFC 2045). */
function wrapBase64(b64: string): string {
  const lines: string[] = []
  for (let i = 0; i < b64.length; i += 76) {
    lines.push(b64.slice(i, i + 76))
  }
  return lines.join('\r\n')
}

/** Read a Blob as a raw base64 string (no data-URL prefix). */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // Strip "data:<mime>;base64," prefix
      const base64 = result.split(',')[1] ?? ''
      resolve(base64)
    }
    reader.onerror = () => reject(new Error('FileReader error'))
    reader.readAsDataURL(blob)
  })
}

interface BuildEmlOptions {
  subject: string
  body: string
  pdfBase64: string
  pdfFilename: string
}

/** Build a standards-compliant multipart/mixed .eml string. */
function buildEml({ subject, body, pdfBase64, pdfFilename }: BuildEmlOptions): string {
  const boundary = `----=_Part_${Date.now()}_${Math.random().toString(36).slice(2)}`
  const CRLF = '\r\n'

  // RFC 2047 encoded-word for the Subject (handles all Unicode locales)
  const subjectEncoded = `=?UTF-8?B?${utf8ToBase64(subject)}?=`

  // Body encoded as UTF-8 base64 (handles non-Latin1 characters safely)
  const bodyB64 = wrapBase64(utf8ToBase64(body))

  // PDF base64 wrapped at 76 chars
  const pdfB64Wrapped = wrapBase64(pdfBase64)

  return [
    `To: `,
    `Subject: ${subjectEncoded}`,
    `X-Unsent: 1`,
    `MIME-Version: 1.0`,
    `Content-Type: multipart/mixed; boundary="${boundary}"`,
    ``,
    `--${boundary}`,
    `Content-Type: text/plain; charset="UTF-8"`,
    `Content-Transfer-Encoding: base64`,
    ``,
    bodyB64,
    ``,
    `--${boundary}`,
    `Content-Type: application/pdf; name="${pdfFilename}"`,
    `Content-Transfer-Encoding: base64`,
    `Content-Disposition: attachment; filename="${pdfFilename}"`,
    ``,
    pdfB64Wrapped,
    ``,
    `--${boundary}--`,
  ].join(CRLF)
}

async function sendToDoctor() {
  sendingToDoctor.value = true
  try {
    // Fetch bearer token
    const token = await requireAuth()

    // Fetch display_name from /api/auth/me. The endpoint wraps the user in a
    // `user` key — read me.user.display_name, not me.display_name.
    let displayName = ''
    try {
      const meRes = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (meRes.ok) {
        const payload = await meRes.json() as { user?: User } & Partial<User>
        displayName = payload.user?.display_name ?? payload.display_name ?? ''
      }
    } catch {
      // Non-critical — fall back to empty string
    }

    // POST the analysis we're already displaying so the PDF mirrors the screen.
    // Daily analyses are generated live and not reliably persisted server-side,
    // so we send what the dashboard holds rather than have the backend re-fetch.
    const res = await fetch(`${API_BASE}/api/health/report/${activeDate.value}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        summary: daily.value?.summary ?? null,
        flags: daily.value?.flags ?? [],
        coach_insight: daily.value?.coach_insight ?? '',
        analysis: daily.value?.analysis ?? '',
        reasoning: daily.value?.reasoning ?? '',
      }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const pdfBlob = await res.blob()

    // Convert PDF blob to raw base64
    const pdfBase64 = await blobToBase64(pdfBlob)

    // Build the .eml
    const pdfFilename = `health-report-${activeDate.value}.pdf`
    const subject = t('health.doctorEmailSubject')
    const body = t('health.doctorEmailBody', { name: displayName || '—' })
    const eml = buildEml({ subject, body, pdfBase64, pdfFilename })

    // Trigger download — the browser associates .eml with the default mail client
    const emlBlob = new Blob([eml], { type: 'message/rfc822' })
    const url = URL.createObjectURL(emlBlob)
    const a = document.createElement('a')
    a.href = url
    a.download = `health-report-${activeDate.value}.eml`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)

    toast(t('health.sentToDoctorReady'), 'success')
  } catch {
    toast(t('health.sendToDoctorError'), 'error')
  } finally {
    sendingToDoctor.value = false
  }
}

onMounted(async () => {
  // Resolve the persistent sync state first, then load the LATEST stored analysis
  // and an anchored trend window — not just "today" — so a previously synced device
  // surfaces its data on every login instead of looking unsynced.
  await fetchStatus()
  const latest = healthStatus.value?.latest_data_date
  if (latest) activeDate.value = latest
  fetchDaily(activeDate.value)
  fetchTrends(trendDays.value, activeDate.value)

  // Show goal-capture modal if the brain doesn't already have a weight goal.
  const existing = await checkWeightGoal()
  if (existing === null) goalPromptOpen.value = true
})
</script>

<template>
  <div style="max-width: var(--content-dashboard); margin: 0 auto;">
    <PageHead title="Health" desc="Upload your health data and your brain turns it into a plain-language summary. Everything stays on your server." />

    <input ref="ahInput" type="file" accept=".zip,.xml" hidden @change="onPickFile" />

    <!-- Loading -->
    <PiCard v-if="dailyStatus === 'loading' || importStatus === 'uploading' || samsungImportStatus === 'uploading'" style="margin-bottom: var(--space-6);">
      <div class="pi-progress pi-progress--thin"><div class="pi-progress__track"><div class="pi-progress__fill" style="width: 40%;" /></div></div>
      <p class="t-secondary" style="font-size: var(--text-sm); margin-top: var(--space-3);">
        {{ importStatus === 'uploading' || samsungImportStatus === 'uploading' ? 'Importing your export and generating your analysis — this can take a minute…' : 'Generating your health analysis…' }}
      </p>
    </PiCard>

    <!-- Empty / first-run -->
    <div v-if="!hasData && dailyStatus !== 'loading' && importStatus !== 'uploading' && samsungImportStatus !== 'uploading'" style="margin-bottom: var(--space-6);">
      <UploadBanner
        tone="amber" icon="health" title="Get your health analysis"
        intro="Upload any of the following and your brain will generate a plain-language summary of your health — no medical background needed to understand it."
        :items="[
          'Blood test results (PDF or image)',
          'Doctor reports or prescriptions',
          'Apple Health / Samsung Health exports (.zip or .xml)',
          'Wearable data from Garmin, Fitbit, or similar',
          'Scale exports or manual weight logs',
        ]"
        note="Your data stays on your server. You can delete everything from Settings → Privacy & data at any time."
      >
        <template #actions>
          <PiButton variant="cta" icon="upload" @click="pickFile">Upload health files</PiButton>
          <PiButton variant="secondary" icon="plus" @click="addDeviceOpen = true">Add a device</PiButton>
        </template>
      </UploadBanner>
    </div>

    <!-- Devices (synced only) + add button -->
    <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-4);">
      <div style="font-family: var(--font-display); font-weight: 600; font-size: var(--text-md);">Devices</div>
      <div style="display: flex; gap: var(--space-2); align-items: center;">
        <PiButton variant="ghost" size="compact" @click="openGuide('ios')">How to export from Apple Health</PiButton>
        <PiButton variant="secondary" size="compact" icon="plus" @click="addDeviceOpen = true">Add device</PiButton>
      </div>
    </div>
    <div v-if="syncedDevices.length" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-8);">
      <DeviceCard
        v-for="d in syncedDevices" :key="d.name"
        :icon="d.icon" :name="d.name" :connected="d.synced" :lastSync="d.lastSync"
        :instructions="d.instructions" :acceptHint="d.acceptHint"
        @files="onDeviceFiles(d, $event)"
      />
    </div>
    <p v-else class="t-secondary" style="font-size: var(--text-sm); margin-bottom: var(--space-8);">
      No devices synced yet. Use <strong>Add device</strong> to upload an export from your wearable or scale.
    </p>

    <!-- Has data but no analysis yet -->
    <PiCard v-if="hasData && !hasAnalysis && dailyStatus !== 'loading'" style="margin-bottom: var(--space-6); border-left: 3px solid var(--brain-amber);">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap;">
        <div>
          <div style="font-family: var(--font-display); font-weight: 600;">Your data is in — generate your analysis</div>
          <p class="t-secondary" style="font-size: var(--text-sm); margin-top: 2px;">We have your metrics. Generate a plain-language summary for {{ latestTrendDate ?? activeDate }}.</p>
        </div>
        <PiButton variant="primary" @click="updateAnalysis">Generate analysis</PiButton>
      </div>
    </PiCard>

    <!-- Populated insights -->
    <template v-if="hasAnalysis">
      <div style="display: flex; justify-content: flex-end; margin-bottom: var(--space-3);">
        <ShareButton kind="health_card" :highlight="healthHighlight" label="Share snapshot" />
      </div>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-4); margin-bottom: var(--space-6);">
        <PiCard v-for="stat in statRow" :key="stat.label">
          <div style="font-family: var(--font-display); font-weight: 600; font-size: 24px; letter-spacing: -0.01em;">{{ stat.value }}</div>
          <div class="t-secondary" style="font-size: 12px;">{{ stat.label }}</div>
        </PiCard>
      </div>

      <div class="pi-insight-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); margin-bottom: var(--space-4);">
        <InsightCard title="Your body at a glance">
          <template #status><StatusPill :kind="glanceStatus.kind">{{ glanceStatus.text }}</StatusPill></template>
          <p class="pi-insight__lead" style="margin-bottom: var(--space-4);">{{ daily?.coach_insight }}</p>
          <div style="display: flex; gap: var(--space-8); flex-wrap: wrap;">
            <div>
              <div class="t-secondary" style="font-size: var(--text-sm); margin-bottom: 4px;">Weight trend</div>
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', color: trendColor, fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 'var(--text-md)' }">
                <PIIcon :name="trendIcon" :size="16" /><span class="t-mono">{{ fmtTrend(trend) }}</span>
              </div>
            </div>
            <div v-if="daily?.summary.progress_to_goal_kg != null && weightGoal !== null">
              <div class="t-secondary" style="font-size: var(--text-sm); margin-bottom: 4px;">To goal ({{ weightGoal }} kg)</div>
              <StatusPill :kind="(daily?.summary.progress_to_goal_kg ?? 1) <= 0 ? 'good' : 'watch'">{{ fmtKg(daily?.summary.progress_to_goal_kg) }}</StatusPill>
            </div>
            <div v-else-if="daily?.summary.progress_to_goal_kg == null && weightGoal === null">
              <div class="t-secondary" style="font-size: var(--text-sm); margin-bottom: 4px;">Weight goal</div>
              <button
                style="font-size: var(--text-sm); color: var(--accent-primary); background: none; border: none; cursor: pointer; padding: 0; font-family: var(--font-body);"
                @click="goalPromptOpen = true"
              >Set a goal</button>
            </div>
          </div>
        </InsightCard>

        <InsightCard title="What your numbers mean">
          <template #footer>
            <button class="pi-show-numbers" @click="showNumbers = !showNumbers">{{ showNumbers ? 'Hide numbers' : 'Show numbers' }}</button>
          </template>
          <InsightLine v-for="(line, i) in numberLines" :key="i" :kind="line.kind" :label="line.label" :text="line.text" :raw="line.raw" :showRaw="showNumbers" />
        </InsightCard>
      </div>

      <div v-if="dataSuggests" style="margin-bottom: var(--space-6);">
        <InsightCard title="What your data suggests"><p class="pi-insight__lead">{{ dataSuggests }}</p></InsightCard>
      </div>

      <PiCard style="margin-bottom: var(--space-6);">
        <div :class="['pi-collapse', chartsOpen ? 'pi-collapse--open' : '']">
          <button type="button" class="pi-collapse__toggle" :aria-expanded="chartsOpen" @click="chartsOpen = !chartsOpen">
            <PIIcon name="chevronRight" :size="14" />Show detailed charts
          </button>
          <div v-if="chartsOpen" class="pi-collapse__body">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-4);">
              <div style="font-family: var(--font-display); font-weight: 500;">Trends</div>
              <div class="pi-pills">
                <button v-for="d in [30, 90]" :key="d" :class="['pi-pill', trendDays === d ? 'pi-pill--active' : '']" @click="trendDays = d">{{ d }}D</button>
              </div>
            </div>
            <div v-if="trendStatus === 'error'" style="color: var(--danger); font-size: var(--text-sm); margin-bottom: var(--space-4);">{{ trendError }}</div>
            <div style="font-family: var(--font-display); font-weight: 500; font-size: var(--text-sm); margin-bottom: var(--space-2);">Weight · last {{ trendDays }} days</div>
            <div style="height: 240px; position: relative; margin-bottom: var(--space-6);"><canvas ref="chartWeightRef" /></div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5); margin-bottom: var(--space-6);">
              <div><div style="font-family: var(--font-display); font-weight: 500; font-size: var(--text-sm); margin-bottom: var(--space-2);">Resting heart rate · last 14 days</div><div style="height: 160px; position: relative;"><canvas ref="chartHrRef" /></div></div>
              <div><div style="font-family: var(--font-display); font-weight: 500; font-size: var(--text-sm); margin-bottom: var(--space-2);">HRV · last 14 days</div><div style="height: 160px; position: relative;"><canvas ref="chartHrvRef" /></div></div>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-5);">
              <div><div style="font-family: var(--font-display); font-weight: 500; font-size: var(--text-sm); margin-bottom: var(--space-2);">Sleep · last 7 days</div><div style="height: 160px; position: relative;"><canvas ref="chartSleepRef" /></div></div>
              <div><div style="font-family: var(--font-display); font-weight: 500; font-size: var(--text-sm); margin-bottom: var(--space-2);">Steps · last 7 days</div><div style="height: 160px; position: relative;"><canvas ref="chartStepsRef" /></div></div>
            </div>
          </div>
        </div>
      </PiCard>

      <div style="display: flex; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap;">
        <div style="display: flex; gap: var(--space-3); flex-wrap: wrap;">
          <PiButton variant="ghost" icon="plus" @click="pickFile">Upload more data</PiButton>
          <PiButton variant="ghost" @click="updateAnalysis">Update analysis</PiButton>
          <PiButton
            variant="primary"
            icon="email"
            :loading="sendingToDoctor"
            :disabled="sendingToDoctor"
            @click="sendToDoctor"
          >{{ sendingToDoctor ? 'Preparing…' : t('health.sendToDoctor') }}</PiButton>
        </div>
        <PiButton variant="danger" icon="trash" @click="confirmDel = true">Delete all health data</PiButton>
      </div>
    </template>
  </div>

  <!-- Add device modal -->
  <Teleport to="body">
    <div v-if="addDeviceOpen" class="pi-modal-overlay" role="dialog" aria-modal="true" @click="addDeviceOpen = false">
      <div class="pi-modal" style="max-width: 600px; max-height: 85vh; overflow: auto;" @click.stop>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-4);">
          <div class="pi-modal__title" style="margin: 0;">Add a device</div>
          <button class="pi-btn pi-btn--icon" aria-label="Close" @click="addDeviceOpen = false"><PIIcon name="close" :size="18" /></button>
        </div>
        <p class="t-secondary" style="font-size: var(--text-sm); margin-bottom: var(--space-5);">
          Pick your device and upload its export. There's no live account link — only the files you choose to share.
        </p>
        <div style="display: grid; grid-template-columns: 1fr; gap: var(--space-4);">
          <DeviceCard
            v-for="d in allDevices" :key="d.name"
            :icon="d.icon" :name="d.name" :connected="d.synced" :lastSync="d.lastSync"
            :instructions="d.instructions" :acceptHint="d.acceptHint"
            @files="onDeviceFiles(d, $event)"
          />
        </div>
      </div>
    </div>
  </Teleport>

  <HealthExportGuide :open="guideOpen" :platform="guidePlatform" @close="guideOpen = false" @update:platform="guidePlatform = $event" />

  <GoalPrompt
    kind="weight"
    :open="goalPromptOpen"
    :saving="goalSaving"
    :error="goalError"
    @close="goalPromptOpen = false"
    @save="onSaveWeightGoal"
  />

  <ConfirmModal
    :open="confirmDel" danger confirmLabel="Delete all health data"
    title="Delete all health data?"
    body="This permanently removes every health file and the insights drawn from them. Your brain keeps everything else. This cannot be undone."
    @close="confirmDel = false" @confirm="deleteAll"
  />
</template>
