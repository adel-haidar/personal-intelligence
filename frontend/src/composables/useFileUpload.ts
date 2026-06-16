import { ref } from 'vue'
import { requireAuth, refreshTokens, hasRefreshToken } from './useAuth'
import { API_BASE } from '../config/env'

export interface UploadFile {
  id:              string
  file:            File
  status:          'queued' | 'uploading' | 'success' | 'error'
  progress:        number
  error?:          string
  serverResponse?: { id: string; filename: string; indexed: boolean }
}

const UPLOAD_URL = `${API_BASE}/api/file`

interface HttpError extends Error {
  httpStatus: number
}

function makeHttpError(status: number, message: string): HttpError {
  return Object.assign(new Error(message), { httpStatus: status })
}

function httpStatusOf(err: unknown): number {
  const e = err as HttpError
  return typeof e?.httpStatus === 'number' ? e.httpStatus : 0
}

export function useFileUpload() {
  const files      = ref<UploadFile[]>([])
  const isDragOver = ref(false)
  let   processing = false

  function doXhr(record: UploadFile, token: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const xhr  = new XMLHttpRequest()
      const form = new FormData()
      form.append('files', record.file)

      xhr.open('POST', UPLOAD_URL)
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          record.progress = Math.round((e.loaded / e.total) * 100)
        }
      }

      xhr.onload = () => {
        if (xhr.status === 200) {
          let saved: { memory_id?: string; filename?: string; status?: string } | undefined
          try {
            saved = (JSON.parse(xhr.responseText) as {
              files?: { memory_id?: string; filename?: string; status?: string }[]
            }).files?.[0]
          } catch { /* leave undefined */ }
          record.serverResponse = {
            id:       saved?.memory_id ?? '',
            filename: saved?.filename ?? record.file.name,
            indexed:  saved?.status === 'ok',
          }
          record.status   = 'success'
          record.progress = 100
          resolve()
        } else {
          let msg = `HTTP ${xhr.status}`
          try { msg = (JSON.parse(xhr.responseText) as { detail?: string }).detail ?? msg } catch {}
          reject(makeHttpError(xhr.status, msg))
        }
      }

      xhr.onerror = () => reject(makeHttpError(0, 'Network error'))
      xhr.send(form)
    })
  }

  async function runUpload(record: UploadFile): Promise<void> {
    record.status   = 'uploading'
    record.progress = 0

    let token: string
    try {
      token = await requireAuth()
    } catch {
      record.status = 'error'
      record.error  = 'Session expired — please re-authenticate'
      return
    }

    try {
      await doXhr(record, token)
    } catch (err) {
      if (httpStatusOf(err) === 401 && hasRefreshToken()) {
        // One retry after a forced token refresh (OAuth sessions only)
        try {
          await refreshTokens()
          token = await requireAuth()
          await doXhr(record, token)
        } catch (retryErr) {
          record.status = 'error'
          record.error  = httpStatusOf(retryErr) === 401
            ? 'Session expired — please re-authenticate'
            : ((retryErr as Error).message ?? 'Upload failed')
        }
      } else {
        record.status = 'error'
        record.error  = (err as Error).message ?? 'Upload failed'
      }
    }
  }

  // Processes queued files one at a time. Non-reentrant: additional calls
  // while running are no-ops — the running loop will pick up new items.
  async function processQueue(): Promise<void> {
    if (processing) return
    processing = true
    try {
      let next: UploadFile | undefined
      while ((next = files.value.find((f) => f.status === 'queued'))) {
        await runUpload(next)
      }
    } finally {
      processing = false
    }
  }

  async function uploadFile(file: File): Promise<void> {
    files.value.push({
      id:       crypto.randomUUID(),
      file,
      status:   'queued',
      progress: 0,
    })
    processQueue() // intentionally not awaited
  }

  function removeFile(id: string): void {
    const idx = files.value.findIndex((f) => f.id === id)
    if (idx !== -1) files.value.splice(idx, 1)
  }

  function clearCompleted(): void {
    files.value = files.value.filter((f) => f.status !== 'success')
  }

  async function uploadAll(): Promise<void> {
    await processQueue()
  }

  return { files, isDragOver, uploadFile, removeFile, clearCompleted, uploadAll }
}
