<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { requireAuth, refreshTokens } from '../composables/useAuth'
import { updateMemory, deleteMemory } from '../composables/useMemories'
import type { UpdateMemoryPayload } from '../composables/useMemories'

import { API_BASE } from '../config/env'

// ── Text memory form ───────────────────────────────────────────
const textTitle   = ref('')
const textContent = ref('')
const textTags    = ref('')
const textSaving  = ref(false)
const textResult  = ref<{ ok: boolean; message: string } | null>(null)

async function saveTextMemory() {
  if (!textTitle.value.trim() || !textContent.value.trim()) return
  textSaving.value = true
  textResult.value = null
  try {
    const token = await requireAuth()
    const tags = textTags.value
      .split(',')
      .map(t => t.trim())
      .filter(Boolean)
    const res = await fetch(`${API_BASE}/api/memory/text`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ title: textTitle.value, content: textContent.value, tags }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail ?? `HTTP ${res.status}`)
    }
    const data = await res.json() as { memory_id: string }
    textResult.value = { ok: true, message: `Saved — ID: ${data.memory_id}` }
    textTitle.value   = ''
    textContent.value = ''
    textTags.value    = ''
    await fetchMemories()
  } catch (err) {
    textResult.value = { ok: false, message: (err as Error).message ?? 'Save failed' }
  } finally {
    textSaving.value = false
  }
}

// ── File upload ────────────────────────────────────────────────
interface UploadState {
  dragging: boolean
  uploading: boolean
  result: { ok: boolean; message: string } | null
}

const upload: UploadState = {
  dragging: false,
  uploading: false,
  result: null,
}
const uploadState = ref<UploadState>({ ...upload })
const fileInputRef = ref<HTMLInputElement>()

function onDragEnter(e: DragEvent) { e.preventDefault(); uploadState.value.dragging = true }
function onDragOver(e: DragEvent)  { e.preventDefault() }
function onDragLeave(e: DragEvent) {
  if (!(e.currentTarget as Element).contains(e.relatedTarget as Node | null))
    uploadState.value.dragging = false
}
async function onDrop(e: DragEvent) {
  e.preventDefault()
  uploadState.value.dragging = false
  const files = Array.from(e.dataTransfer?.files ?? [])
  if (files[0]) await uploadFile(files[0])
}
async function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await uploadFile(file)
}

async function uploadFile(file: File) {
  uploadState.value.uploading = true
  uploadState.value.result = null
  try {
    let token: string
    try {
      token = await requireAuth()
    } catch {
      await refreshTokens()
      token = await requireAuth()
    }
    const form = new FormData()
    form.append('files', file)
    const res = await fetch(`${API_BASE}/api/file`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail ?? `HTTP ${res.status}`)
    }
    const data = await res.json() as { filename: string; memory_id: string }
    uploadState.value.result = { ok: true, message: `${data.filename} saved — ID: ${data.memory_id}` }
    await fetchMemories()
  } catch (err) {
    uploadState.value.result = { ok: false, message: (err as Error).message ?? 'Upload failed' }
  } finally {
    uploadState.value.uploading = false
  }
}

// ── Memory browser ─────────────────────────────────────────────
interface MemoryItem {
  id: string
  title: string
  tags: string[]
  created_at: string
  updated_at?: string
  content: string
}

const memories       = ref<MemoryItem[]>([])
const total          = ref(0)
const currentPage    = ref(1)
const totalPages     = ref(1)
const filterQuery    = ref('')
const loading        = ref(false)
const expandedIds    = ref<Set<string>>(new Set())

async function fetchMemories() {
  loading.value = true
  try {
    const token = await requireAuth()
    const params = new URLSearchParams({
      page: String(currentPage.value),
      page_size: '20',
    })
    if (filterQuery.value.trim()) params.set('q', filterQuery.value.trim())
    const res = await fetch(`${API_BASE}/api/memory?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json() as {
      items: MemoryItem[]
      total: number
      page: number
      pages: number
    }
    memories.value    = data.items
    total.value       = data.total
    currentPage.value = data.page
    totalPages.value  = data.pages
  } catch (err) {
    console.error('Failed to fetch memories:', err)
  } finally {
    loading.value = false
  }
}

function toggleExpand(id: string) {
  if (expandedIds.value.has(id)) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
}

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins  = Math.floor(diff / 60_000)
  const hours = Math.floor(diff / 3_600_000)
  const days  = Math.floor(diff / 86_400_000)
  if (mins < 2)   return 'just now'
  if (mins < 60)  return `${mins} min ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7)   return `${days} days ago`
  return new Date(iso).toLocaleDateString()
}

function formatFull(iso: string): string {
  return new Date(iso).toLocaleString()
}

function prevPage() {
  if (currentPage.value > 1) { currentPage.value--; fetchMemories() }
}
function nextPage() {
  if (currentPage.value < totalPages.value) { currentPage.value++; fetchMemories() }
}
function onFilterInput() {
  currentPage.value = 1
  fetchMemories()
}

// ── Delete ─────────────────────────────────────────────────────
const confirmDeleteId = ref<string | null>(null)

function startDelete(id: string, e: Event) {
  e.stopPropagation()
  confirmDeleteId.value = id
}

function cancelDelete(e: Event) {
  e.stopPropagation()
  confirmDeleteId.value = null
}

async function confirmDelete(id: string, e: Event) {
  e.stopPropagation()
  try {
    await deleteMemory(id)
    memories.value = memories.value.filter(m => m.id !== id)
    total.value = Math.max(0, total.value - 1)
    if (expandedIds.value.has(id)) expandedIds.value.delete(id)
    confirmDeleteId.value = null
  } catch (err) {
    console.error('Delete failed:', err)
    confirmDeleteId.value = null
  }
}

// ── Edit modal ─────────────────────────────────────────────────
const editingMemory = ref<MemoryItem | null>(null)
const editTitle     = ref('')
const editContent   = ref('')
const editTags      = ref('')
const editAppend    = ref(false)
const editSaving    = ref(false)
const editResult    = ref<{ ok: boolean; message: string } | null>(null)

watch(editAppend, (appending) => {
  if (appending) {
    editContent.value = ''
  } else {
    editContent.value = editingMemory.value?.content ?? ''
  }
})

function startEdit(m: MemoryItem, e: Event) {
  e.stopPropagation()
  editingMemory.value = m
  editTitle.value     = m.title
  editContent.value   = m.content
  editTags.value      = m.tags.join(', ')
  editAppend.value    = false
  editResult.value    = null
}

function closeEdit() {
  editingMemory.value = null
  editResult.value    = null
}

async function submitEdit() {
  if (!editingMemory.value) return
  editSaving.value = true
  editResult.value = null
  try {
    const tags = editTags.value.split(',').map(t => t.trim()).filter(Boolean)
    const payload: UpdateMemoryPayload = {}
    if (editTitle.value !== editingMemory.value.title) payload.title = editTitle.value
    if (editAppend.value) {
      if (editContent.value.trim()) {
        payload.content = editContent.value
        payload.append_content = true
      }
    } else if (editContent.value !== editingMemory.value.content) {
      payload.content = editContent.value
    }
    if (JSON.stringify(tags) !== JSON.stringify(editingMemory.value.tags)) payload.tags = tags

    const updated = await updateMemory(editingMemory.value.id, payload)
    const idx = memories.value.findIndex(m => m.id === editingMemory.value!.id)
    if (idx !== -1) {
      memories.value[idx] = {
        ...memories.value[idx],
        title:   updated.title,
        content: updated.content,
        tags:    updated.tags,
        updated_at: updated.updated_at ?? undefined,
      }
    }
    editResult.value = { ok: true, message: 'UPDATED SUCCESSFULLY' }
    setTimeout(closeEdit, 900)
  } catch (err) {
    editResult.value = { ok: false, message: (err as Error).message ?? 'Update failed' }
  } finally {
    editSaving.value = false
  }
}

onMounted(fetchMemories)
</script>

<template>
  <div class="memory-section">

    <!-- ── Zone 1: Input Cards ─────────────────────────────── -->
    <div class="cards-grid">

      <!-- Card A: Text Memory -->
      <div class="card">
        <div class="card-header">
          <span class="card-tag">INPUT</span>
          <span class="card-title">NEW TEXT MEMORY</span>
        </div>
        <div class="card-body">
          <div class="field">
            <label class="field-label">TITLE</label>
            <input
              v-model="textTitle"
              class="field-input"
              placeholder="Memory title"
              :disabled="textSaving"
            />
          </div>
          <div class="field">
            <label class="field-label">CONTENT</label>
            <textarea
              v-model="textContent"
              class="field-textarea"
              placeholder="Memory content…"
              :disabled="textSaving"
            />
          </div>
          <div class="field">
            <label class="field-label">TAGS <span class="field-hint">(comma-separated)</span></label>
            <input
              v-model="textTags"
              class="field-input"
              placeholder="tag1, tag2, tag3"
              :disabled="textSaving"
            />
          </div>
          <div
            v-if="textResult"
            class="inline-result"
            :class="textResult.ok ? 'inline-result--ok' : 'inline-result--err'"
          >{{ textResult.message }}</div>
        </div>
        <div class="card-footer">
          <button
            class="btn btn--primary"
            :disabled="textSaving || !textTitle.trim() || !textContent.trim()"
            @click="saveTextMemory"
          >
            {{ textSaving ? 'SAVING…' : 'SAVE MEMORY' }}
          </button>
        </div>
      </div>

      <!-- Card B: File Upload -->
      <div class="card">
        <div class="card-header">
          <span class="card-tag">UPLOAD</span>
          <span class="card-title">UPLOAD FILE TO MEMORY</span>
        </div>
        <div class="card-body card-body--upload">
          <div
            class="drop-zone"
            :class="{ 'drop-zone--over': uploadState.dragging, 'drop-zone--busy': uploadState.uploading }"
            role="button"
            tabindex="0"
            aria-label="Drop a file or click to browse"
            @click="fileInputRef?.click()"
            @keydown.enter="fileInputRef?.click()"
            @dragenter="onDragEnter"
            @dragover="onDragOver"
            @dragleave="onDragLeave"
            @drop="onDrop"
          >
            <input ref="fileInputRef" type="file" hidden @change="onFileInput" />
            <svg class="drop-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <polyline points="12,4 12,16" stroke-linecap="square" />
              <polyline points="8,8 12,4 16,8" stroke-linecap="square" stroke-linejoin="miter" />
              <line x1="4" y1="20" x2="20" y2="20" stroke-linecap="square" />
            </svg>
            <p class="drop-label">
              {{ uploadState.uploading ? 'UPLOADING…' : 'DROP FILE HERE OR CLICK TO BROWSE' }}
            </p>
            <p class="drop-hint">PDF · TXT · MD · DOCX · CSV · JSON · PNG · JPG</p>
          </div>
          <div
            v-if="uploadState.result"
            class="inline-result"
            :class="uploadState.result.ok ? 'inline-result--ok' : 'inline-result--err'"
          >{{ uploadState.result.message }}</div>
        </div>
        <div class="card-footer" />
      </div>

    </div>

    <!-- ── Zone 2: Memory Browser ─────────────────────────── -->
    <div class="browser">

      <!-- Filter bar -->
      <div class="filter-bar">
        <input
          v-model="filterQuery"
          class="filter-input"
          placeholder="Filter by title or tag…"
          @input="onFilterInput"
        />
        <button class="refresh-btn" :disabled="loading" title="Refresh" @click="fetchMemories">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
            <path d="M13.5 8A5.5 5.5 0 1 1 8 2.5"/>
            <polyline points="8,2.5 11,2.5 11,5.5"/>
          </svg>
        </button>
      </div>

      <!-- Table -->
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th class="th th--title">TITLE</th>
              <th class="th th--tags">TAGS</th>
              <th class="th th--date">SAVED AT</th>
              <th class="th th--actions">ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <template v-if="loading">
              <tr>
                <td colspan="4" class="td td--empty">LOADING…</td>
              </tr>
            </template>
            <template v-else-if="memories.length === 0">
              <tr>
                <td colspan="4" class="td td--empty">NO MEMORIES FOUND</td>
              </tr>
            </template>
            <template v-else>
              <template v-for="m in memories" :key="m.id">
                <tr
                  class="tr"
                  :class="{ 'tr--expanded': expandedIds.has(m.id) }"
                  @click="toggleExpand(m.id)"
                >
                  <td class="td td--title">{{ m.title }}</td>
                  <td class="td td--tags">
                    <span v-for="tag in m.tags" :key="tag" class="tag">{{ tag }}</span>
                  </td>
                  <td class="td td--date" :title="formatFull(m.created_at)">
                    {{ formatRelative(m.created_at) }}
                  </td>
                  <td class="td td--actions" @click.stop>
                    <template v-if="confirmDeleteId === m.id">
                      <button class="action-confirm" @click="confirmDelete(m.id, $event)">YES</button>
                      <button class="action-cancel" @click="cancelDelete($event)">NO</button>
                    </template>
                    <template v-else>
                      <button class="action-btn" title="Edit memory" @click="startEdit(m, $event)">
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
                          <path d="M11.5 2.5l2 2-8 8H3.5v-2l8-8z"/>
                          <path d="M10 4l2 2"/>
                        </svg>
                      </button>
                      <button class="action-btn action-btn--delete" title="Delete memory" @click="startDelete(m.id, $event)">
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
                          <path d="M3 3l10 10M13 3L3 13"/>
                        </svg>
                      </button>
                    </template>
                  </td>
                </tr>
                <tr v-if="expandedIds.has(m.id)" class="tr-detail">
                  <td colspan="4" class="td td--content">{{ m.content }}</td>
                </tr>
              </template>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination">
        <button class="page-btn" :disabled="currentPage <= 1" @click="prevPage">← PREVIOUS</button>
        <span class="page-info">PAGE {{ currentPage }} OF {{ totalPages }}</span>
        <button class="page-btn" :disabled="currentPage >= totalPages" @click="nextPage">NEXT →</button>
      </div>

    </div>
  </div>

  <!-- ── Edit modal ──────────────────────────────────────────── -->
  <Teleport to="body">
    <div v-if="editingMemory" class="modal-backdrop" @click.self="closeEdit">
      <div class="modal">
        <div class="modal-header">
          <span class="card-tag">EDIT</span>
          <span class="modal-title">EDIT MEMORY</span>
          <button class="modal-close" @click="closeEdit">✕</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label class="field-label">TITLE</label>
            <input v-model="editTitle" class="field-input" :disabled="editSaving" />
          </div>
          <div class="field">
            <label class="field-label">{{ editAppend ? 'CONTENT TO APPEND' : 'CONTENT' }}</label>
            <textarea
              v-model="editContent"
              class="field-textarea field-textarea--tall"
              :placeholder="editAppend ? 'Enter text to append below existing content…' : ''"
              :disabled="editSaving"
            />
          </div>
          <div class="field">
            <label class="field-label">TAGS <span class="field-hint">(comma-separated)</span></label>
            <input v-model="editTags" class="field-input" :disabled="editSaving" />
          </div>
          <label class="append-label">
            <input type="checkbox" v-model="editAppend" :disabled="editSaving" class="append-check" />
            <span class="append-text">APPEND TO EXISTING CONTENT</span>
          </label>
          <p v-if="editAppend" class="append-note">
            New content will be appended below the existing text.
          </p>
          <div
            v-if="editResult"
            class="inline-result"
            :class="editResult.ok ? 'inline-result--ok' : 'inline-result--err'"
          >{{ editResult.message }}</div>
        </div>
        <div class="modal-footer">
          <button class="btn" :disabled="editSaving" @click="closeEdit">CANCEL</button>
          <button class="btn btn--primary" :disabled="editSaving" @click="submitEdit">
            {{ editSaving ? 'SAVING…' : 'SAVE CHANGES' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* ── Layout ── */
.memory-section { display: flex; flex-direction: column; gap: 32px; }

/* ── Cards grid ── */
.cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 760px) {
  .cards-grid { grid-template-columns: 1fr; }
}

/* ── Card ── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 16px 20px 14px;
  border-bottom: 1px solid var(--border);
}

.card-tag {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.14em;
  color: var(--text-muted);
  border: 1px solid var(--border);
  padding: 2px 6px;
}

.card-title {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
}

.card-body {
  padding: 20px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-body--upload {
  justify-content: center;
}

.card-footer {
  padding: 0 20px 20px;
  min-height: 52px;
  display: flex;
  align-items: flex-end;
}

/* ── Form fields ── */
.field { display: flex; flex-direction: column; gap: 6px; }

.field-label {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
}

.field-hint {
  font-weight: 400;
  color: var(--text-muted);
  opacity: 0.7;
}

.field-input,
.field-textarea {
  background: var(--bg-base);
  border: 1px solid var(--border);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 8px 10px;
  outline: none;
  transition: border-color 0.1s;
  resize: vertical;
}

.field-textarea {
  min-height: 120px;
}

.field-textarea--tall {
  min-height: 180px;
}

.field-input:focus,
.field-textarea:focus {
  border-color: var(--accent-primary);
}

.field-input:disabled,
.field-textarea:disabled {
  opacity: 0.5;
}

/* ── Inline result ── */
.inline-result {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.04em;
  padding: 6px 8px;
  border: 1px solid;
  word-break: break-all;
}

.inline-result--ok  { color: var(--status-active);  border-color: var(--status-active); }
.inline-result--err { color: var(--status-error); border-color: var(--status-error); }

/* ── Buttons ── */
.btn {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.09em;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 8px 20px;
  cursor: pointer;
  transition: border-color 0.1s, color 0.1s;
}

.btn:hover:not(:disabled) {
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.btn:disabled { opacity: 0.3; cursor: not-allowed; }

.btn--primary {
  color: var(--accent-primary);
  border-color: var(--accent-primary);
}

.btn--primary:hover:not(:disabled) {
  background: rgba(74, 127, 165, 0.08);
}

/* ── Drop zone ── */
.drop-zone {
  border: 1px dashed var(--border);
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  user-select: none;
  transition: border-color 0.12s, background 0.12s;
  outline: none;
}

.drop-zone:hover,
.drop-zone--over {
  border-style: solid;
  border-color: var(--accent-primary);
  background: rgba(74, 127, 165, 0.04);
}

.drop-zone--busy { opacity: 0.6; pointer-events: none; }

.drop-zone:focus-visible {
  outline: 1px solid var(--accent-primary);
  outline-offset: -1px;
}

.drop-icon {
  width: 24px;
  height: 24px;
  color: var(--text-muted);
  margin-bottom: 14px;
}

.drop-zone--over .drop-icon { color: var(--accent-primary); }

.drop-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.drop-hint {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

/* ── Browser ── */
.browser { display: flex; flex-direction: column; gap: 0; }

.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.filter-input {
  flex: 1;
  background: var(--bg-base);
  border: 1px solid var(--border);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 7px 10px;
  outline: none;
  transition: border-color 0.1s;
}

.filter-input:focus { border-color: var(--accent-primary); }

.refresh-btn {
  width: 32px;
  height: 32px;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  flex-shrink: 0;
  transition: border-color 0.1s, color 0.1s;
}

.refresh-btn:hover:not(:disabled) {
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.refresh-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.refresh-btn svg { width: 14px; height: 14px; }

/* ── Table ── */
.table-wrap {
  border: 1px solid var(--border);
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
}

.th {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
  text-align: left;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  white-space: nowrap;
}

.th--title   { width: 36%; }
.th--tags    { width: 28%; }
.th--date    { width: 18%; }
.th--actions { width: 18%; text-align: center; }

.tr {
  cursor: pointer;
  transition: background 0.1s;
}

.tr:hover { background: var(--elevated); }
.tr--expanded { background: var(--elevated); }
.tr + .tr { border-top: 1px solid var(--border); }

.td {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 10px 14px;
  color: var(--text-primary);
  vertical-align: middle;
}

.td--title {
  max-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.td--tags { white-space: normal; }

.td--date {
  color: var(--text-secondary);
  font-size: 10px;
  white-space: nowrap;
}

.td--empty {
  text-align: center;
  color: var(--text-muted);
  font-size: 10px;
  letter-spacing: 0.1em;
  padding: 32px;
}

.td--actions {
  text-align: center;
  white-space: nowrap;
}

/* Tag chips */
.tag {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  border: 1px solid var(--border);
  padding: 1px 5px;
  margin: 1px 2px;
  white-space: nowrap;
}

/* Expanded content row */
.tr-detail { background: var(--bg-base); }

.td--content {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  border-top: 1px solid var(--border);
  padding: 14px 20px;
}

/* ── Pagination ── */
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0 0;
}

.page-btn {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
  background: none;
  border: 1px solid var(--border);
  padding: 6px 14px;
  cursor: pointer;
  transition: border-color 0.1s, color 0.1s;
}

.page-btn:hover:not(:disabled) {
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.page-btn:disabled { opacity: 0.3; cursor: not-allowed; }

.page-info {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
}

/* ── Action buttons ── */
.action-btn {
  background: none;
  border: 1px solid transparent;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.1s, color 0.1s;
}

.action-btn:hover {
  border-color: var(--border);
  color: var(--text-secondary);
}

.action-btn--delete:hover {
  color: var(--status-error);
  border-color: var(--status-error);
}

.action-btn svg { width: 12px; height: 12px; }

.action-confirm,
.action-cancel {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.08em;
  padding: 3px 7px;
  cursor: pointer;
  border: 1px solid;
  background: none;
}

.action-confirm {
  color: var(--status-error);
  border-color: var(--status-error);
  margin-right: 4px;
}

.action-confirm:hover { background: rgba(240, 68, 68, 0.1); }

.action-cancel {
  color: var(--text-muted);
  border-color: var(--border);
}

.action-cancel:hover {
  color: var(--text-secondary);
  border-color: var(--text-secondary);
}

/* ── Edit modal ── */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: var(--surface);
  border: 1px solid var(--border);
  width: min(560px, 90vw);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 16px 20px 14px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.modal-title {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
  flex: 1;
}

.modal-close {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 0 0 0 8px;
  line-height: 1;
  transition: color 0.1s;
}

.modal-close:hover { color: var(--text-primary); }

.modal-body {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.modal-footer {
  padding: 0 20px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.append-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.append-check {
  accent-color: var(--accent-primary);
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.append-text {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
}

.append-note {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  border-left: 2px solid var(--border);
  padding-left: 8px;
  line-height: 1.5;
}
</style>
