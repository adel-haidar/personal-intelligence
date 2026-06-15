<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import BrainPulse from './BrainPulse.vue'
import PIIcon from './PIIcon.vue'
import PiButton from './PiButton.vue'

const props = defineProps<{ t: Record<string, any> }>()
const emit = defineEmits<{ close: [] }>()

const pw = ref('')
const pw2 = ref('')
const loading = ref(false)
const strength = () => pw.value.length >= 16 ? 3 : pw.value.length >= 12 ? 2 : pw.value.length >= 6 ? 1 : 0
const dot = (i: number) => i < strength() ? (strength() === 3 ? 'var(--success)' : 'var(--brain-amber)') : 'var(--border-medium)'

function submit(e: Event) {
  e.preventDefault()
  loading.value = true
  setTimeout(() => {
    window.open('https://app.private-internet.io/register?plan=cloud', '_blank')
    loading.value = false
    emit('close')
  }, 900)
}

function onKey(e: KeyboardEvent) { if (e.key === 'Escape') emit('close') }
onMounted(() => {
  document.addEventListener('keydown', onKey)
  document.body.style.overflow = 'hidden'
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})

const m = props.t.modal.cloud
</script>

<template>
  <div class="mk-overlay" @click.self="emit('close')">
    <div class="mk-modal" role="dialog" aria-modal="true">
      <div class="mk-modal__head">
        <div style="display:flex;align-items:center;gap:var(--space-3)">
          <BrainPulse :size="28" />
          <h2 class="mk-modal__title">{{ m.title }}</h2>
        </div>
        <button class="pi-btn pi-btn--icon" :aria-label="t.mobileMenu.close" @click="emit('close')">
          <PIIcon name="close" :size="18" />
        </button>
      </div>
      <p class="mk-modal__sub">{{ m.sub }}</p>
      <form class="mk-modal__fields" @submit="submit">
        <div class="pi-field">
          <label class="pi-label">{{ m.name }}</label>
          <div class="pi-input-wrap"><input class="pi-input" placeholder="Adel Haidar" required /></div>
        </div>
        <div class="pi-field">
          <label class="pi-label">{{ m.email }}</label>
          <div class="pi-input-wrap"><input class="pi-input" type="email" placeholder="you@yourserver.com" required /></div>
        </div>
        <div class="pi-field">
          <label class="pi-label">{{ m.pw }}</label>
          <div class="pi-input-wrap">
            <input class="pi-input" type="password" v-model="pw" placeholder="••••••••••••" required />
          </div>
          <div class="mk-strength">
            <span v-for="i in [0,1,2]" :key="i" :style="{ background: dot(i) }" />
          </div>
        </div>
        <div class="pi-field">
          <label class="pi-label">{{ m.pw2 }}</label>
          <div class="pi-input-wrap">
            <input class="pi-input" :class="pw2 && pw2 !== pw ? 'pi-input--error' : ''" type="password" v-model="pw2" placeholder="••••••••••••" required />
          </div>
        </div>
        <p class="mk-modal__note">{{ m.note }}</p>
        <PiButton variant="cta" :block="true" type="submit" :loading="loading" icon="arrowRight">{{ m.cta }}</PiButton>
      </form>
      <div class="mk-modal__foot">
        <a href="https://app.private-internet.io/login" target="_blank" rel="noopener">{{ m.signin }} →</a>
      </div>
    </div>
  </div>
</template>
