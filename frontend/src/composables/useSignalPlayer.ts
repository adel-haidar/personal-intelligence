/**
 * App-level SIGNAL playback state (module singleton, like useAria).
 *
 * Holds the currently-playing video so the player can persist across navigation
 * and minimise to a docked mini-player (rendered in App.vue, above the router)
 * while playback continues. `expanded` toggles between the full-screen overlay
 * and the mini bar — the same <video> element stays mounted across the switch.
 */
import { ref } from 'vue'
import type { Video } from './useContent'

const current = ref<Video | null>(null)
const related = ref<Video[]>([])
const category = ref('')
const expanded = ref(false)

export function useSignalPlayer() {
  function play(video: Video, opts?: { related?: Video[]; category?: string }) {
    current.value = video
    related.value = opts?.related ?? []
    category.value = opts?.category ?? ''
    expanded.value = true
  }
  function minimize() { expanded.value = false }
  function expand() { if (current.value) expanded.value = true }
  function close() {
    current.value = null
    related.value = []
    category.value = ''
    expanded.value = false
  }
  return { current, related, category, expanded, play, minimize, expand, close }
}
