/**
 * Accessible modal focus management (WCAG 2.4.3 Focus Order, 2.1.2 No Keyboard Trap).
 *
 * While the dialog is open it:
 *  - remembers what had focus, and restores it when the dialog closes/unmounts,
 *  - moves focus to the first focusable element inside the dialog,
 *  - cycles Tab / Shift+Tab within the dialog (so focus can't leak to the page
 *    behind the overlay),
 *  - calls `onEscape` when Escape is pressed.
 *
 * Works for both open-prop dialogs (pass a getter/ref for `isOpen`) and dialogs
 * the parent mounts conditionally with v-if (pass `() => true`).
 *
 *   const dialogEl = ref<HTMLElement | null>(null)
 *   useFocusTrap(dialogEl, () => props.open, { onEscape: () => emit('close') })
 */
import { watch, nextTick, onBeforeUnmount, type Ref } from 'vue'

interface Options {
  onEscape?: () => void
}

const FOCUSABLE =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function useFocusTrap(
  container: Ref<HTMLElement | null>,
  isOpen: Ref<boolean> | (() => boolean),
  opts: Options = {},
) {
  let prevFocus: HTMLElement | null = null
  const getOpen = typeof isOpen === 'function' ? isOpen : () => isOpen.value

  function focusables(): HTMLElement[] {
    const root = container.value
    if (!root) return []
    return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      // offsetParent === null ⇒ hidden (display:none / visibility) — skip it.
      (el) => !el.hasAttribute('disabled') && el.offsetParent !== null,
    )
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      opts.onEscape?.()
      return
    }
    if (e.key !== 'Tab') return
    const items = focusables()
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement as HTMLElement
    if (e.shiftKey && active === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }

  function release() {
    window.removeEventListener('keydown', onKey)
    prevFocus?.focus?.()
    prevFocus = null
  }

  watch(
    getOpen,
    (open) => {
      if (open) {
        prevFocus = document.activeElement as HTMLElement
        window.addEventListener('keydown', onKey)
        nextTick(() => focusables()[0]?.focus())
      } else {
        release()
      }
    },
    { immediate: true },
  )

  // Covers v-if-mounted dialogs that unmount without their open flag flipping.
  onBeforeUnmount(release)
}
