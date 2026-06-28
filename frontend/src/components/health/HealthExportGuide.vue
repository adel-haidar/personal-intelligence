<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import PIIcon from '../ui/PIIcon.vue'
import PiButton from '../ui/PiButton.vue'
import IconButton from '../ui/IconButton.vue'
import PhoneMock from './PhoneMock.vue'
import { useFocusTrap } from '../../composables/useFocusTrap'

// ── Props / emits ──────────────────────────────────────────────────────────
interface Props {
  open: boolean
  platform: 'ios' | 'android'
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:platform', p: 'ios' | 'android'): void
}>()

// ── Body-scroll lock ───────────────────────────────────────────────────────
// (Escape, focus trap and focus restore are handled by useFocusTrap below.)
let prevOverflow = ''

watch(
  () => props.open,
  (open) => {
    if (open) {
      prevOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = prevOverflow
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  document.body.style.overflow = prevOverflow
})

const dialogEl = ref<HTMLElement | null>(null)
useFocusTrap(dialogEl, () => props.open, { onEscape: () => emit('close') })

// ── Step content (static) ─────────────────────────────────────────────────
interface Step {
  title: string
  desc: string
  screen: 'ios1' | 'ios2' | 'ios3' | 'ios4' | 'and1' | 'and2' | 'and3' | 'and4'
}

const GUIDES: Record<'ios' | 'android', { label: string; steps: Step[] }> = {
  ios: {
    label: 'iPhone',
    steps: [
      {
        screen: 'ios1',
        title: 'Open Health, tap your photo',
        desc: 'Launch the Health app and tap your profile picture in the top-right corner.',
      },
      {
        screen: 'ios2',
        title: 'Choose "Export All Health Data"',
        desc: 'Scroll to the bottom of your profile and tap Export All Health Data.',
      },
      {
        screen: 'ios3',
        title: 'Confirm the export',
        desc: 'Tap Export. Your iPhone prepares a .zip archive — this can take a few minutes.',
      },
      {
        screen: 'ios4',
        title: 'Save, then upload it here',
        desc: 'Save to Files (or AirDrop to your computer), then upload the .zip below.',
      },
    ],
  },
  android: {
    label: 'Android',
    steps: [
      {
        screen: 'and1',
        title: 'Open Samsung Health settings',
        desc: 'Open Samsung Health and tap the Settings (gear) icon at the top.',
      },
      {
        screen: 'and2',
        title: 'Tap "Download personal data"',
        desc: 'In Settings, choose Download personal data.',
      },
      {
        screen: 'and3',
        title: 'Download your archive',
        desc: 'Tap Download. Samsung Health bundles your data into a single file.',
      },
      {
        screen: 'and4',
        title: 'Find it, then upload it here',
        desc: 'Open your Downloads, then upload the archive below.',
      },
    ],
  },
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="pi-modal-overlay"
      @click="emit('close')"
    >
      <div
        ref="dialogEl"
        class="pi-modal"
        role="dialog"
        aria-modal="true"
        aria-label="How to export your health data"
        @click.stop
      >
        <!-- ── Header ────────────────────────────────────────────────────── -->
        <div class="pi-modal__head">
          <div style="flex: 1; min-width: 0;">
            <div class="pi-modal__title">Export your health data</div>
            <div class="pi-modal__sub">
              Four steps on your phone. Your file is read into your brain on your own server — nothing is sent anywhere else.
            </div>
          </div>

          <!-- segmented toggle -->
          <div class="pi-seg" role="tablist" aria-label="Platform">
            <button
              v-for="key in (['ios', 'android'] as const)"
              :key="key"
              role="tab"
              :aria-selected="platform === key"
              :class="['pi-seg__btn', platform === key ? 'pi-seg__btn--active' : '']"
              @click="emit('update:platform', key)"
            >
              <PIIcon :name="key === 'ios' ? 'device' : 'watch'" :size="14" />
              {{ GUIDES[key].label }}
            </button>
          </div>

          <IconButton icon="close" label="Close" @click="emit('close')" />
        </div>

        <!-- ── Body ─────────────────────────────────────────────────────── -->
        <div class="pi-modal__body">
          <div class="pi-guide-grid">
            <div
              v-for="(step, i) in GUIDES[platform].steps"
              :key="platform + i"
              class="pi-step"
            >
              <div class="pi-step__phone">
                <span class="pi-step__num" aria-hidden="true">{{ i + 1 }}</span>
                <PhoneMock>
                  <!-- iOS step 1: Summary + avatar highlight -->
                  <template v-if="step.screen === 'ios1'">
                    <div class="ph-nav" style="align-items: flex-start;">
                      <div class="ph-h1">Summary</div>
                      <div style="position: relative;">
                        <div class="ph-avatar ph-hot ph-hot--circle">A</div>
                        <span class="ph-tap" style="top: -10px; right: -6px;">Tap</span>
                      </div>
                    </div>
                    <div class="ph-grp">Favorites</div>
                    <div class="ph-list">
                      <div class="ph-row">
                        <span class="ph-ic" style="background: #FF2D55;">♥</span>
                        <span class="ph-row__t">Heart Rate</span>
                        <span style="font-size: 11px; font-weight: 600; color: var(--ph-text);">72</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-ic" style="background: #FF9500;">🦶</span>
                        <span class="ph-row__t">Steps</span>
                        <span style="font-size: 11px; font-weight: 600; color: var(--ph-text);">8,240</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-ic" style="background: #5856D6;">🛏</span>
                        <span class="ph-row__t">Sleep</span>
                        <span style="font-size: 11px; font-weight: 600; color: var(--ph-text);">7h</span>
                      </div>
                    </div>
                  </template>

                  <!-- iOS step 2: Profile + Export All row highlighted -->
                  <template v-else-if="step.screen === 'ios2'">
                    <div class="ph-nav">
                      <span class="ph-back">‹ Summary</span>
                      <span class="ph-title">Profile</span>
                      <span style="width: 30px;" />
                    </div>
                    <div class="ph-list" style="margin-bottom: 8px;">
                      <div class="ph-row">
                        <span class="ph-ic" style="background: #8E8E93;">◔</span>
                        <span class="ph-row__t">Health Checklist</span>
                        <span class="ph-chev">›</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-ic" style="background: #34C759;">✓</span>
                        <span class="ph-row__t">Health Records</span>
                        <span class="ph-chev">›</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-ic" style="background: #FF3B30;">＋</span>
                        <span class="ph-row__t">Medical ID</span>
                        <span class="ph-chev">›</span>
                      </div>
                    </div>
                    <div class="ph-grp">Export</div>
                    <div class="ph-list">
                      <div class="ph-row ph-hot">
                        <span class="ph-ic" style="background: #0A84FF;">⤓</span>
                        <span class="ph-row__t" style="font-weight: 600;">Export All Health Data</span>
                      </div>
                    </div>
                    <span class="ph-tap" style="position: static; align-self: flex-end; margin-top: 6px;">Tap this</span>
                  </template>

                  <!-- iOS step 3: Alert "Export?" with Export button highlighted -->
                  <template v-else-if="step.screen === 'ios3'">
                    <div style="filter: blur(.4px); opacity: .5;">
                      <div class="ph-grp">Export</div>
                      <div class="ph-list">
                        <div class="ph-row">
                          <span class="ph-row__t">Export All Health Data</span>
                        </div>
                      </div>
                    </div>
                    <div class="ph-dim">
                      <div class="ph-alert">
                        <div class="ph-alert__b">
                          <div class="ph-alert__t">Export?</div>
                          <div class="ph-alert__x">Preparing your data may take a few minutes.</div>
                        </div>
                        <div class="ph-alert__btns">
                          <div class="ph-abtn">Cancel</div>
                          <div class="ph-abtn ph-abtn--primary ph-hot" style="border-radius: 0;">Export</div>
                        </div>
                      </div>
                    </div>
                  </template>

                  <!-- iOS step 4: Share sheet + Save to Files highlighted -->
                  <template v-else-if="step.screen === 'ios4'">
                    <div style="opacity: .55;">
                      <div class="ph-h1" style="font-size: 15px;">export.zip</div>
                      <div style="font-size: 10px; color: var(--ph-sub);">Ready to share</div>
                    </div>
                    <div class="ph-sheet">
                      <div class="ph-grab" />
                      <div class="ph-apps">
                        <span class="ph-app" />
                        <span class="ph-app" />
                        <span class="ph-app" />
                        <span class="ph-app" />
                      </div>
                      <div class="ph-list">
                        <div class="ph-row ph-hot">
                          <span class="ph-ic" style="background: #0A84FF;">🗂</span>
                          <span class="ph-row__t" style="font-weight: 600;">Save to Files</span>
                        </div>
                        <div class="ph-row">
                          <span class="ph-ic" style="background: #34C759;">⇅</span>
                          <span class="ph-row__t">AirDrop</span>
                        </div>
                      </div>
                    </div>
                  </template>

                  <!-- Android step 1: Samsung Health home + gear highlighted -->
                  <template v-else-if="step.screen === 'and1'">
                    <div class="ph-nav" style="align-items: center;">
                      <span class="ph-title" style="font-size: 13px;">Samsung Health</span>
                      <div style="position: relative;">
                        <span class="ph-ic ph-hot ph-hot--circle" style="background: #5A5A70; width: 24px; height: 24px;">⚙</span>
                        <span class="ph-tap" style="top: -10px; right: -6px;">Tap</span>
                      </div>
                    </div>
                    <div style="display: flex; gap: 7px; margin-bottom: 7px;">
                      <div class="ph-tile">
                        <div class="ph-tile__n">8,240</div>
                        <div class="ph-tile__l">Steps</div>
                      </div>
                      <div class="ph-tile">
                        <div class="ph-tile__n">72</div>
                        <div class="ph-tile__l">BPM</div>
                      </div>
                    </div>
                    <div class="ph-tile">
                      <div class="ph-tile__n">7h 14m</div>
                      <div class="ph-tile__l">Sleep last night</div>
                    </div>
                  </template>

                  <!-- Android step 2: Settings list + Download personal data highlighted -->
                  <template v-else-if="step.screen === 'and2'">
                    <div class="ph-nav">
                      <span class="ph-back" style="color: var(--ph-text);">‹</span>
                      <span class="ph-title">Settings</span>
                      <span style="width: 14px;" />
                    </div>
                    <div class="ph-list">
                      <div class="ph-row">
                        <span class="ph-row__t">Notifications</span>
                        <span class="ph-chev">›</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-row__t">Permissions</span>
                        <span class="ph-chev">›</span>
                      </div>
                      <div class="ph-row ph-hot">
                        <span class="ph-row__t" style="font-weight: 600;">Download personal data</span>
                        <span class="ph-chev">›</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-row__t">About Samsung Health</span>
                        <span class="ph-chev">›</span>
                      </div>
                    </div>
                    <span class="ph-tap" style="position: static; align-self: flex-end; margin-top: 6px;">Tap this</span>
                  </template>

                  <!-- Android step 3: Download screen + green Download button highlighted -->
                  <template v-else-if="step.screen === 'and3'">
                    <div class="ph-nav">
                      <span class="ph-back" style="color: var(--ph-text);">‹</span>
                      <span class="ph-title">Download data</span>
                      <span style="width: 14px;" />
                    </div>
                    <div class="ph-card" style="margin-bottom: 7px;">
                      <div style="font-size: 11px; font-weight: 600; margin-bottom: 4px; color: var(--ph-text);">Personal data</div>
                      <div style="font-size: 10px; color: var(--ph-sub); line-height: 1.5;">Bundle your steps, heart rate, sleep and more into a single file you can download.</div>
                    </div>
                    <div class="ph-btn ph-btn--android ph-hot">Download</div>
                  </template>

                  <!-- Android step 4: Downloads list + samsung_health.zip highlighted -->
                  <template v-else-if="step.screen === 'and4'">
                    <div class="ph-nav">
                      <span class="ph-title" style="font-size: 13px;">Downloads</span>
                    </div>
                    <div class="ph-list">
                      <div class="ph-row ph-hot">
                        <span class="ph-zip">ZIP</span>
                        <span class="ph-row__t" style="font-weight: 600;">samsung_health.zip</span>
                      </div>
                      <div class="ph-row">
                        <span class="ph-zip" style="background: #bcbcc4;">PDF</span>
                        <span class="ph-row__t">report.pdf</span>
                      </div>
                    </div>
                    <span class="ph-tap" style="position: static; align-self: flex-start; margin-top: 6px;">Your export</span>
                  </template>
                </PhoneMock>
              </div>

              <div class="pi-step__cap">
                <div class="pi-step__cap-t">{{ step.title }}</div>
                <div class="pi-step__cap-d">{{ step.desc }}</div>
              </div>
            </div>
          </div>

          <!-- fallback note -->
          <div style="margin-top: var(--space-6); display: flex; align-items: center; gap: var(--space-2); color: var(--text-tertiary); font-size: var(--text-sm);">
            <PIIcon name="help" :size="15" />
            Using Google Fit or Health Connect? Open Settings &rarr; Data &amp; privacy &rarr; Export your data, then upload the file the same way.
          </div>
        </div>

        <!-- ── Footer ────────────────────────────────────────────────────── -->
        <div class="pi-modal__foot">
          <span style="display: inline-flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: var(--text-sm);">
            <PIIcon name="shield" :size="15" />
            Processed only on your server.
          </span>
          <PiButton variant="primary" @click="emit('close')">Got it</PiButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>
