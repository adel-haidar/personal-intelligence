import { ref } from 'vue'
import { requireAuth } from './useAuth'
import { API_BASE } from '../config/env'

export type GoalKind = 'weight' | 'savings'

interface MemoryItem {
  id: string
  content: string
}

const WEIGHT_MARKER = 'TARGET_WEIGHT_KG='
const SAVINGS_MARKER = 'ANNUAL_SAVINGS_GOAL='

// ── Cached goal values (reactive, per session) ───────────────────────────────
const _weightGoal = ref<number | null>(null)
const _savingsGoal = ref<{ amount: number; currency: string } | null>(null)
const _weightChecked = ref(false)
const _savingsChecked = ref(false)

function parseWeightFromMemories(items: MemoryItem[]): number | null {
  for (const m of items) {
    const match = m.content.match(/TARGET_WEIGHT_KG=([\d.]+)/)
    if (match) return parseFloat(match[1])
  }
  return null
}

function parseSavingsFromMemories(items: MemoryItem[]): { amount: number; currency: string } | null {
  for (const m of items) {
    const match = m.content.match(/ANNUAL_SAVINGS_GOAL=([\d.]+)\s+([A-Z]{3})/)
    if (match) return { amount: parseFloat(match[1]), currency: match[2] }
  }
  return null
}

async function fetchAllGoalMemories(): Promise<MemoryItem[]> {
  const token = await requireAuth()
  const params = new URLSearchParams({ page: '1', page_size: '50' })
  const res = await fetch(`${API_BASE}/api/memory?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) return []
  const data = await res.json() as { items: MemoryItem[] }
  return data.items ?? []
}

export async function checkWeightGoal(): Promise<number | null> {
  if (_weightChecked.value) return _weightGoal.value
  const items = await fetchAllGoalMemories()
  _weightGoal.value = parseWeightFromMemories(items)
  _weightChecked.value = true
  return _weightGoal.value
}

export async function checkSavingsGoal(): Promise<{ amount: number; currency: string } | null> {
  if (_savingsChecked.value) return _savingsGoal.value
  const items = await fetchAllGoalMemories()
  _savingsGoal.value = parseSavingsFromMemories(items)
  _savingsChecked.value = true
  return _savingsGoal.value
}

export async function saveWeightGoal(kg: number): Promise<void> {
  const token = await requireAuth()
  const content = `My target weight is ${kg} kg.\nTARGET_WEIGHT_KG=${kg}`
  const res = await fetch(`${API_BASE}/api/memory/text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      title: 'Health Goal — Target Weight',
      content,
      tags: ['health', 'goal', 'weight'],
    }),
  })
  if (!res.ok) throw new Error(`save weight goal failed: ${res.status}`)
  _weightGoal.value = kg
  _weightChecked.value = true
}

export async function saveSavingsGoal(amount: number, currency: string): Promise<void> {
  const token = await requireAuth()
  const content = `My annual savings goal is ${amount} ${currency}.\nANNUAL_SAVINGS_GOAL=${amount} ${currency}`
  const res = await fetch(`${API_BASE}/api/memory/text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      title: 'Financial Goal — Annual Savings',
      content,
      tags: ['finances', 'goal', 'savings'],
    }),
  })
  if (!res.ok) throw new Error(`save savings goal failed: ${res.status}`)
  _savingsGoal.value = { amount, currency }
  _savingsChecked.value = true
}

// Exposed reactive refs for consuming views
export function useWeightGoal() {
  return { weightGoal: _weightGoal }
}

export function useSavingsGoal() {
  return { savingsGoal: _savingsGoal }
}

// Clear session cache (useful for testing / logout)
export function clearGoalCache() {
  _weightGoal.value = null
  _savingsGoal.value = null
  _weightChecked.value = false
  _savingsChecked.value = false
}

export { WEIGHT_MARKER, SAVINGS_MARKER }
