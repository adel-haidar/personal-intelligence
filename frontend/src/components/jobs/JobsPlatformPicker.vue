<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useJobsStore } from '../../composables/useJobsStore'

const store = useJobsStore()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

// Countries with their discovered platforms, in the user's chosen order.
const groups = computed(() =>
  store.state.selectedRunCountries.map(code => ({
    code,
    name: store.state.availableCountries.find(c => c.code === code)?.name ?? code,
    platforms: store.state.availablePlatforms[code] ?? [],
  })),
)

const hasCountries = computed(() => store.state.selectedRunCountries.length > 0)
const selectedCount = computed(() => store.state.selectedRunPlatforms.length)

const buttonLabel = computed(() => {
  if (!hasCountries.value) return 'Platforms'
  const n = selectedCount.value
  if (n === 0) return 'All platforms'
  if (n === 1) {
    for (const g of groups.value) {
      const p = g.platforms.find(pl => pl.platform_key === store.state.selectedRunPlatforms[0])
      if (p) return p.display_name
    }
    return '1 platform'
  }
  return `${n} platforms`
})

function isSelected(key: string): boolean {
  return store.state.selectedRunPlatforms.includes(key)
}

function toggle(key: string): void {
  store.toggleRunPlatform(key)
}

function toggleOpen(): void {
  if (!hasCountries.value) return
  open.value = !open.value
  if (open.value && Object.keys(store.state.availablePlatforms).length === 0) {
    store.loadPlatforms()
  }
}

function onDocClick(e: MouseEvent): void {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div ref="root" class="platform-picker">
    <button
      type="button"
      class="picker-btn"
      :class="{ active: selectedCount > 0 }"
      :disabled="!hasCountries"
      :title="hasCountries ? 'Choose which job boards to search' : 'Select at least one country first'"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggleOpen"
    >
      <span class="picker-label">{{ buttonLabel }}</span>
      <span v-if="selectedCount > 1" class="picker-count">{{ selectedCount }}</span>
    </button>

    <div v-if="open" class="picker-panel" role="listbox">
      <p class="picker-hint">
        Pick boards to narrow the search. None selected = every board for the country.
      </p>

      <div v-if="store.state.platformsLoading" class="picker-empty">Loading platforms…</div>

      <template v-else>
        <div v-for="g in groups" :key="g.code" class="picker-group">
          <div class="group-head">
            <span class="group-name">{{ g.name }}</span>
            <span class="group-code">{{ g.code }}</span>
          </div>
          <p v-if="g.platforms.length === 0" class="group-empty">
            No platforms discovered yet — they appear after the nightly scan.
          </p>
          <ul v-else class="picker-list">
            <li
              v-for="p in g.platforms"
              :key="p.platform_key"
              class="picker-item"
              role="option"
              :aria-selected="isSelected(p.platform_key)"
              @click="toggle(p.platform_key)"
            >
              <span class="picker-check" :class="{ on: isSelected(p.platform_key) }" aria-hidden="true">
                <svg v-if="isSelected(p.platform_key)" width="11" height="9" viewBox="0 0 11 9" fill="none">
                  <path d="M1 4.5L4 7.5L10 1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>
              <span class="picker-name">{{ p.display_name }}</span>
              <span v-if="p.needs_key" class="picker-badge" title="Needs an API key">key</span>
              <span v-else-if="!p.available" class="picker-badge muted" title="Not confirmed in the last scan">unverified</span>
            </li>
          </ul>
        </div>

        <button v-if="store.state.platformsNeedKey" class="guide-link" @click="store.openSetupGuide()">
          Some platforms need an API key — view setup guide →
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.platform-picker { position: relative; }

.picker-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 8px);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  padding: 7px 12px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.picker-btn:hover:not(:disabled), .picker-btn[aria-expanded="true"] {
  border-color: var(--border-medium);
  color: var(--text-primary);
}
.picker-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.picker-btn.active { color: var(--text-primary); }

.picker-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--accent-primary);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.picker-panel {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 50;
  width: 280px;
  max-height: 360px;
  display: flex;
  flex-direction: column;
  background: var(--background-elevated, var(--background-surface));
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-md, 10px);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.28);
  overflow-y: auto;
  padding-bottom: 6px;
}

.picker-hint {
  margin: 0;
  padding: 10px 12px 8px;
  font-size: 12px;
  color: var(--text-tertiary, var(--text-secondary));
  border-bottom: 1px solid var(--border-subtle);
}

.picker-group { padding: 4px 4px 0; }

.group-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 8px 8px 4px;
}
.group-name { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.group-code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-tertiary, var(--text-secondary));
  letter-spacing: 0.04em;
}
.group-empty {
  margin: 0;
  padding: 2px 8px 8px;
  font-size: 12px;
  color: var(--text-tertiary, var(--text-secondary));
}

.picker-list { list-style: none; margin: 0; padding: 0; }

.picker-empty {
  padding: 14px 12px;
  color: var(--text-tertiary, var(--text-secondary));
  font-size: 13px;
}

.picker-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border-radius: var(--radius-sm, 8px);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
}
.picker-item:hover { background: var(--background-surface-hover, rgba(127,127,127,0.08)); color: var(--text-primary); }
.picker-item[aria-selected="true"] { color: var(--text-primary); }

.picker-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 1px solid var(--border-medium);
  border-radius: 4px;
  color: #fff;
  flex-shrink: 0;
}
.picker-check.on { background: var(--accent-primary); border-color: var(--accent-primary); }

.picker-name { flex: 1; }

.picker-badge {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(245, 166, 35, 0.16);
  color: var(--brain-amber, #F5A623);
}
.picker-badge.muted {
  background: rgba(127, 127, 127, 0.14);
  color: var(--text-tertiary, var(--text-secondary));
}

.guide-link {
  display: block;
  width: calc(100% - 16px);
  margin: 8px 8px 4px;
  padding: 8px 10px;
  background: transparent;
  border: 1px dashed var(--border-medium);
  border-radius: var(--radius-sm, 8px);
  color: var(--accent-primary);
  font-family: var(--font-sans);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.guide-link:hover { border-color: var(--accent-primary); }
</style>
