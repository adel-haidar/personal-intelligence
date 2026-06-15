<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSite } from '@/composables/useSite'
import type { LangCode } from '@/locales/index'
import { messages } from '@/locales/index'

import NavSection from '@/components/NavSection.vue'
import HeroSection from '@/components/HeroSection.vue'
import ProblemSection from '@/components/ProblemSection.vue'
import BrainSection from '@/components/BrainSection.vue'
import ModulesSection from '@/components/ModulesSection.vue'
import HowSection from '@/components/HowSection.vue'
import PrivacySection from '@/components/PrivacySection.vue'
import HostingSection from '@/components/HostingSection.vue'
import PricingSection from '@/components/PricingSection.vue'
import HardwareSection from '@/components/HardwareSection.vue'
import FaqSection from '@/components/FaqSection.vue'
import FooterSection from '@/components/FooterSection.vue'
import CloudModal from '@/components/CloudModal.vue'
import SelfModal from '@/components/SelfModal.vue'
import MobileMenu from '@/components/MobileMenu.vue'

import { scrollToId } from '@/composables/useSite'

const { locale } = useI18n()
const { theme, lang, isScrolled, toggleTheme, setLang } = useSite()

// Get translation object directly from messages (avoids vue-i18n path resolution complexity)
const t = computed(() => messages[lang.value as LangCode] as Record<string, any>)

// Modal state
const modalType = ref<'cloud' | 'self' | null>(null)
const mobileOpen = ref(false)

function openModal(type: 'cloud' | 'self') {
  modalType.value = type
}

function handleStart() {
  scrollToId('hosting')
}

function handleSignin() {
  window.open('https://app.private-internet.io/login', '_blank')
}
</script>

<template>
  <div
    class="site"
    :data-theme="theme"
    :data-lang="lang"
    :dir="lang === 'ar' ? 'rtl' : 'ltr'"
  >
    <NavSection
      :t="t"
      :lang="lang"
      :scrolled="isScrolled"
      :theme="theme"
      @toggle-theme="toggleTheme"
      @set-lang="(code: LangCode) => setLang(code)"
      @open-mobile="mobileOpen = true"
      @signin="handleSignin"
      @start="handleStart"
    />

    <HeroSection :t="t" @start="handleStart" />
    <ProblemSection :t="t" />
    <BrainSection :t="t" />
    <ModulesSection :t="t" />
    <HowSection :t="t" />
    <PrivacySection :t="t" />
    <HostingSection :t="t" @open-modal="openModal" />
    <PricingSection :t="t" />
    <HardwareSection :t="t" />
    <FaqSection :t="t" />
    <FooterSection
      :t="t"
      :lang="lang"
      :theme="theme"
      @set-lang="(code: LangCode) => setLang(code)"
      @toggle-theme="toggleTheme"
    />

    <!-- Modals -->
    <CloudModal v-if="modalType === 'cloud'" :t="t" @close="modalType = null" />
    <SelfModal v-if="modalType === 'self'" :t="t" @close="modalType = null" />

    <!-- Mobile menu -->
    <MobileMenu
      v-if="mobileOpen"
      :t="t"
      :lang="lang"
      :theme="theme"
      @close="mobileOpen = false"
      @toggle-theme="toggleTheme"
      @set-lang="(code: LangCode) => setLang(code)"
      @signin="handleSignin"
      @start="handleStart"
    />
  </div>
</template>
