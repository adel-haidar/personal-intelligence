import { ref } from 'vue'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'pi-theme'

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t
}

// Singleton state — created once, shared across all callers.
const theme = ref<Theme>(
  (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? 'dark'
)

// Apply immediately on module load (before mount) so there is no flash.
applyTheme(theme.value)

function setTheme(t: Theme) {
  theme.value = t
  applyTheme(t)
  localStorage.setItem(STORAGE_KEY, t)
}

function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

export function useTheme() {
  return { theme, setTheme, toggleTheme }
}
