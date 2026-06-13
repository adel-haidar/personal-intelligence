import { ref, inject } from 'vue'

export type ToastKind = 'success' | 'warning' | 'error'

export interface Toast {
  id: string
  msg: string
  kind: ToastKind
}

export type PushToast = (msg: string, kind?: ToastKind) => void

export const TOAST_KEY = Symbol('toast') as symbol & { __brand: 'toast' }

/** Internal state — used by ToastProvider only */
export function useToastState() {
  const toasts = ref<Toast[]>([])

  const push: PushToast = (msg, kind = 'success') => {
    const id = Math.random().toString(36).slice(2)
    toasts.value.push({ id, msg, kind })
    setTimeout(() => {
      toasts.value = toasts.value.filter(t => t.id !== id)
    }, 3000)
  }

  return { toasts, push }
}

/** Consumer composable — call inside components that need to fire toasts */
export function useToast(): PushToast {
  const push = inject<PushToast>(TOAST_KEY)
  if (!push) {
    // Graceful noop when no provider is present
    return () => {}
  }
  return push
}
