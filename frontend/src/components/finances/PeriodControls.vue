<script setup lang="ts">
import { ref, computed } from 'vue'
import Pills from '../ui/Pills.vue'
import PiSelect from '../ui/PiSelect.vue'
import PiTextarea from '../ui/PiTextarea.vue'
import PiButton from '../ui/PiButton.vue'
import type { AnalysisParams } from '../../composables/useBankAdviser'

defineProps<{ loading?: boolean; hasResult?: boolean }>()
const emit = defineEmits<{ run: [params: AnalysisParams] }>()

const CURRENT_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: Math.max(1, CURRENT_YEAR - 2023) }, (_, i) => String(2024 + i))
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const MODE_OPTIONS = [
  { value: 'ytd', label: 'Year to date' },
  { value: 'single', label: 'Single month' },
  { value: 'range', label: 'Range' },
]

const mode      = ref<'ytd' | 'single' | 'range'>('ytd')
const fromYear  = ref(String(CURRENT_YEAR))
const fromMonth = ref(MONTHS[0])
const toYear    = ref(String(CURRENT_YEAR))
const toMonth   = ref(MONTHS[new Date().getMonth()])
const context   = ref('')

const pad  = (n: number) => String(n).padStart(2, '0')
const mIdx = (m: string) => MONTHS.indexOf(m) + 1

const params = computed<AnalysisParams>(() => {
  if (mode.value === 'ytd') return { mode: 'ytd', context: context.value }
  if (mode.value === 'single') {
    return { mode: 'single', period_from: `${fromYear.value}-${pad(mIdx(fromMonth.value))}`, context: context.value }
  }
  return {
    mode: 'range',
    period_from: `${fromYear.value}-${pad(mIdx(fromMonth.value))}`,
    period_to: `${toYear.value}-${pad(mIdx(toMonth.value))}`,
    context: context.value,
  }
})
</script>

<template>
  <div class="fin-controls">
    <div class="fin-control-row">
      <span class="fin-control-label">Period</span>
      <Pills :options="MODE_OPTIONS" :modelValue="mode" @update:modelValue="(v) => (mode = v as 'ytd' | 'single' | 'range')" />
    </div>

    <div v-if="mode !== 'ytd'" class="fin-control-row">
      <span class="fin-control-label">From</span>
      <PiSelect :options="YEARS" v-model="fromYear" />
      <PiSelect :options="MONTHS" v-model="fromMonth" />
    </div>

    <div v-if="mode === 'range'" class="fin-control-row">
      <span class="fin-control-label">To</span>
      <PiSelect :options="YEARS" v-model="toYear" />
      <PiSelect :options="MONTHS" v-model="toMonth" />
    </div>

    <div class="fin-control-row">
      <span class="fin-control-label">Context</span>
      <PiTextarea v-model="context" placeholder="Optional — extra instructions for the analysis…" style="flex: 1; min-height: 60px;" />
    </div>

    <div>
      <PiButton variant="primary" :loading="loading" @click="emit('run', params)">
        {{ hasResult ? 'Re-run analysis' : 'Run analysis' }}
      </PiButton>
    </div>
  </div>
</template>
