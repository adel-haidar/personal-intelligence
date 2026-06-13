<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import BrainPulse from '../components/ui/BrainPulse.vue'
import PIIcon from '../components/ui/PIIcon.vue'
import ModeToggle from '../components/ui/ModeToggle.vue'

const router = useRouter()
const mobileMenuOpen = ref(false)

function goRegister(plan?: string) {
  router.push(plan ? `/register?plan=${plan}` : '/register')
}

const VALUE_COLUMNS = [
  {
    icon: 'brain',
    title: 'Everything learns from your memory',
    body: 'Every interaction feeds a personal knowledge graph unique to you — not pooled with millions of strangers.',
  },
  {
    icon: 'shield',
    title: 'Your data never leaves your server',
    body: 'Models run on your infrastructure. We cannot read, sell, or lose your data because we never hold it.',
  },
  {
    icon: 'spark',
    title: 'The more you share, the smarter it gets',
    body: 'Health stats, emails, documents, thoughts — the richer your brain, the more useful the AI becomes.',
  },
]

const MODULES = [
  {
    icon: 'pulse',
    name: 'Pulse',
    desc: 'An AI social feed built around your life — posts, ideas, and updates generated from your own memory.',
  },
  {
    icon: 'signal',
    name: 'Signal',
    desc: 'AI-generated videos on topics that matter to you, narrated and assembled automatically every day.',
  },
  {
    icon: 'health',
    name: 'Health + Finances',
    desc: 'Insights drawn from your own wearables and documents — Apple Health, bank statements, all private.',
  },
]

const PLANS = [
  {
    key: 'free',
    name: 'Free',
    price: '€0',
    period: '',
    cta: 'Get started free',
    highlight: false,
    features: [
      '50 memories',
      '5 posts per week',
      '2 videos per week',
      '500 MB storage',
    ],
  },
  {
    key: 'personal',
    name: 'Personal',
    price: '€9',
    period: '/mo',
    cta: 'Start Personal',
    highlight: true,
    features: [
      'Unlimited memories',
      '20 posts per week',
      '7 videos per week',
      '5 GB storage',
    ],
  },
  {
    key: 'pro',
    name: 'Pro',
    price: '€19',
    period: '/mo',
    cta: 'Start Pro',
    highlight: false,
    features: [
      'Unlimited memories',
      'Unlimited posts',
      'Unlimited videos',
      '20 GB storage',
    ],
  },
]
</script>

<template>
  <div class="landing">
    <!-- ── Sticky header ─────────────────────────────────────────────────── -->
    <header class="landing-header">
      <div class="landing-container landing-header__inner">
        <a href="/" class="landing-logo" aria-label="Private Internet home">
          <BrainPulse :size="28" aria-hidden="true" />
          <span class="landing-logo__name">Private Internet</span>
        </a>

        <nav class="landing-nav" aria-label="Main navigation">
          <router-link to="/about" class="landing-nav__link">How it works</router-link>
        </nav>

        <div class="landing-header__actions">
          <ModeToggle :withLabel="false" />
          <router-link to="/login" class="landing-btn landing-btn--ghost">Sign in</router-link>
          <button class="landing-btn landing-btn--cta" @click="goRegister()">
            Create account <PIIcon name="arrowRight" :size="14" />
          </button>
        </div>

        <!-- Mobile: hamburger triggers a full-width menu -->
        <button
          class="landing-mobile-menu-btn"
          :aria-expanded="mobileMenuOpen"
          aria-controls="mobile-menu"
          aria-label="Toggle navigation"
          @click="mobileMenuOpen = !mobileMenuOpen"
        >
          <span class="landing-burger" :class="{ open: mobileMenuOpen }" aria-hidden="true" />
        </button>
      </div>

      <!-- Mobile menu -->
      <div v-if="mobileMenuOpen" id="mobile-menu" class="landing-mobile-menu">
        <router-link to="/about" class="landing-mobile-menu__link" @click="mobileMenuOpen = false">How it works</router-link>
        <router-link to="/login" class="landing-mobile-menu__link" @click="mobileMenuOpen = false">Sign in</router-link>
        <button class="landing-btn landing-btn--cta landing-mobile-menu__cta" @click="goRegister(); mobileMenuOpen = false">
          Create account
        </button>
      </div>
    </header>

    <main>
      <!-- ── Hero ───────────────────────────────────────────────────────── -->
      <section class="landing-hero" aria-labelledby="hero-headline">
        <div class="landing-container landing-hero__inner">
          <div class="landing-hero__pulse" aria-hidden="true">
            <BrainPulse :size="64" :slow="true" />
          </div>

          <h1 id="hero-headline" class="landing-hero__headline">
            Your AI. Your server.<br class="landing-br-desktop" /> Your rules.
          </h1>

          <p class="landing-hero__sub t-serif">
            A personal AI platform that runs on your own infrastructure — not in a corporation's cloud.
          </p>

          <div class="landing-hero__actions">
            <button class="landing-btn landing-btn--cta landing-btn--lg" @click="goRegister()">
              Create free account
            </button>
            <a href="#how-it-works" class="landing-btn landing-btn--ghost landing-btn--lg">
              See how it works
              <PIIcon name="chevronDown" :size="14" />
            </a>
          </div>
        </div>
      </section>

      <!-- ── Value columns ──────────────────────────────────────────────── -->
      <section id="how-it-works" class="landing-values" aria-labelledby="values-heading">
        <div class="landing-container">
          <h2 id="values-heading" class="landing-section-title">Built for privacy. Designed to be useful.</h2>
          <div class="landing-values__grid">
            <article v-for="col in VALUE_COLUMNS" :key="col.icon" class="landing-value-col">
              <div class="landing-value-col__icon" aria-hidden="true">
                <BrainPulse v-if="col.icon === 'brain'" :size="28" />
                <PIIcon v-else :name="col.icon" :size="28" />
              </div>
              <h3 class="landing-value-col__title">{{ col.title }}</h3>
              <p class="landing-value-col__body t-secondary">{{ col.body }}</p>
            </article>
          </div>
        </div>
      </section>

      <!-- ── Module cards ───────────────────────────────────────────────── -->
      <section class="landing-modules" aria-labelledby="modules-heading">
        <div class="landing-container">
          <h2 id="modules-heading" class="landing-section-title">Three modules. One brain.</h2>
          <div class="landing-modules__grid">
            <article v-for="mod in MODULES" :key="mod.name" class="landing-module-card">
              <div class="landing-module-card__icon" aria-hidden="true">
                <PIIcon :name="mod.icon" :size="24" />
              </div>
              <h3 class="landing-module-card__name">{{ mod.name }}</h3>
              <p class="landing-module-card__desc t-secondary">{{ mod.desc }}</p>
            </article>
          </div>
        </div>
      </section>

      <!-- ── Pricing ────────────────────────────────────────────────────── -->
      <section class="landing-pricing" aria-labelledby="pricing-heading">
        <div class="landing-container">
          <h2 id="pricing-heading" class="landing-section-title">Simple, honest pricing</h2>
          <p class="landing-pricing__sub t-secondary">
            Start for free. No card required. Upgrade when you need more.
          </p>

          <div class="landing-pricing__grid">
            <article
              v-for="plan in PLANS"
              :key="plan.key"
              class="landing-pricing-card"
              :class="{ 'landing-pricing-card--highlight': plan.highlight }"
              :aria-label="`${plan.name} plan`"
            >
              <div v-if="plan.highlight" class="landing-pricing-card__badge">
                Most popular
              </div>

              <div class="landing-pricing-card__header">
                <span class="landing-pricing-card__name">{{ plan.name }}</span>
                <div class="landing-pricing-card__price">
                  <span class="landing-pricing-card__amount">{{ plan.price }}</span>
                  <span v-if="plan.period" class="landing-pricing-card__period t-tertiary">{{ plan.period }}</span>
                </div>
              </div>

              <ul class="landing-pricing-card__features" role="list">
                <li v-for="feat in plan.features" :key="feat" class="landing-pricing-card__feature">
                  <PIIcon name="check" :size="14" class="landing-check-icon" aria-hidden="true" />
                  <span>{{ feat }}</span>
                </li>
              </ul>

              <button
                class="landing-btn landing-pricing-card__cta"
                :class="plan.highlight ? 'landing-btn--cta' : 'landing-btn--secondary'"
                @click="goRegister(plan.key)"
              >
                {{ plan.cta }}
              </button>
            </article>
          </div>
        </div>
      </section>
    </main>

    <!-- ── Footer ─────────────────────────────────────────────────────── -->
    <footer class="landing-footer" role="contentinfo">
      <div class="landing-container landing-footer__inner">
        <span class="landing-footer__brand t-secondary">Private Internet</span>
        <nav class="landing-footer__links" aria-label="Footer links">
          <a
            href="https://github.com/personal-intelligence"
            target="_blank"
            rel="noopener noreferrer"
            class="landing-footer__link"
          >GitHub</a>
          <router-link to="/about" class="landing-footer__link">How it works</router-link>
          <router-link to="/about" class="landing-footer__link">Privacy</router-link>
        </nav>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* ── Layout shell ─────────────────────────────────────────────────────────── */
.landing {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--background-page);
  color: var(--text-primary);
}

.landing-container {
  width: 100%;
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 var(--space-6);
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.landing-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--background-page);
  border-bottom: 1px solid var(--border-subtle);
  backdrop-filter: blur(8px);
}

.landing-header__inner {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  height: 60px;
}

.landing-logo {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  text-decoration: none;
  color: var(--text-primary);
  flex-shrink: 0;
}

.landing-logo__name {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--text-base);
  letter-spacing: -0.01em;
}

.landing-nav {
  display: flex;
  gap: var(--space-6);
  margin-right: auto;
}

.landing-nav__link {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  text-decoration: none;
  transition: color 0.15s var(--ease);
}
.landing-nav__link:hover { color: var(--text-primary); }

.landing-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.landing-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  border: none;
  text-decoration: none;
  transition: background 0.15s var(--ease), color 0.15s var(--ease), border-color 0.15s var(--ease);
  white-space: nowrap;
}

.landing-btn--cta {
  background: var(--accent-primary);
  color: #fff;
}
.landing-btn--cta:hover { background: var(--accent-hover); }

.landing-btn--secondary {
  background: var(--background-raised);
  color: var(--text-primary);
  border: 1px solid var(--border-medium);
}
.landing-btn--secondary:hover { border-color: var(--accent-primary); color: var(--accent-primary); }

.landing-btn--ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}
.landing-btn--ghost:hover { border-color: var(--border-medium); color: var(--text-primary); }

.landing-btn--lg {
  padding: 12px 24px;
  font-size: var(--text-base);
}

/* ── Mobile menu ─────────────────────────────────────────────────────────── */
.landing-mobile-menu-btn {
  display: none;
  padding: var(--space-2);
  background: none;
  border: none;
  cursor: pointer;
  margin-left: auto;
}

.landing-burger {
  display: block;
  width: 20px;
  height: 2px;
  background: var(--text-primary);
  position: relative;
  transition: background 0.2s;
}
.landing-burger::before,
.landing-burger::after {
  content: '';
  position: absolute;
  left: 0;
  width: 20px;
  height: 2px;
  background: var(--text-primary);
  transition: transform 0.2s, top 0.2s;
}
.landing-burger::before { top: -6px; }
.landing-burger::after { top: 6px; }
.landing-burger.open { background: transparent; }
.landing-burger.open::before { top: 0; transform: rotate(45deg); }
.landing-burger.open::after { top: 0; transform: rotate(-45deg); }

.landing-mobile-menu {
  border-top: 1px solid var(--border-subtle);
  padding: var(--space-4) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.landing-mobile-menu__link {
  font-size: var(--text-base);
  color: var(--text-secondary);
  text-decoration: none;
  padding: var(--space-2) 0;
}
.landing-mobile-menu__link:hover { color: var(--text-primary); }

.landing-mobile-menu__cta {
  align-self: flex-start;
  margin-top: var(--space-2);
}

/* ── Hero ────────────────────────────────────────────────────────────────── */
.landing-hero {
  padding: var(--space-16) 0 var(--space-12);
  text-align: center;
}

.landing-hero__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-6);
}

.landing-hero__pulse {
  display: flex;
  justify-content: center;
}

.landing-hero__headline {
  font-family: var(--font-display);
  font-size: clamp(var(--text-xl), 5vw, var(--text-2xl));
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.15;
  color: var(--text-primary);
}

.landing-br-desktop { display: none; }
@media (min-width: 640px) { .landing-br-desktop { display: inline; } }

.landing-hero__sub {
  font-size: var(--text-md);
  color: var(--text-secondary);
  max-width: 560px;
  line-height: 1.7;
  font-style: italic;
}

.landing-hero__actions {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  justify-content: center;
}

/* ── Section shared ──────────────────────────────────────────────────────── */
.landing-section-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 600;
  text-align: center;
  margin-bottom: var(--space-8);
  color: var(--text-primary);
}

/* ── Value columns ───────────────────────────────────────────────────────── */
.landing-values {
  padding: var(--space-12) 0;
  border-top: 1px solid var(--border-subtle);
}

.landing-values__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-8);
}

.landing-value-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: center;
  text-align: center;
}

.landing-value-col__icon {
  color: var(--brain-amber);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md);
  background: var(--brain-amber-surface);
  flex-shrink: 0;
}

.landing-value-col__title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.landing-value-col__body {
  font-size: var(--text-sm);
  line-height: 1.65;
}

/* ── Module cards ────────────────────────────────────────────────────────── */
.landing-modules {
  padding: var(--space-12) 0;
  border-top: 1px solid var(--border-subtle);
}

.landing-modules__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-4);
}

.landing-module-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6);
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.landing-module-card__icon {
  color: var(--accent-primary);
}

.landing-module-card__name {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.landing-module-card__desc {
  font-size: var(--text-sm);
  line-height: 1.65;
}

/* ── Pricing ─────────────────────────────────────────────────────────────── */
.landing-pricing {
  padding: var(--space-12) 0;
  border-top: 1px solid var(--border-subtle);
}

.landing-pricing__sub {
  text-align: center;
  font-size: var(--text-sm);
  margin-top: calc(-1 * var(--space-6));
  margin-bottom: var(--space-8);
}

.landing-pricing__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-4);
  align-items: start;
}

.landing-pricing-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-6);
  background: var(--background-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  position: relative;
}

.landing-pricing-card--highlight {
  border-color: var(--accent-primary);
  background: var(--accent-surface);
}

.landing-pricing-card__badge {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--accent-primary);
  color: #fff;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 3px 12px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.landing-pricing-card__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.landing-pricing-card__name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.landing-pricing-card__price {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
}

.landing-pricing-card__amount {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
}

.landing-pricing-card__period {
  font-size: var(--text-sm);
}

.landing-pricing-card__features {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  flex: 1;
}

.landing-pricing-card__feature {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.landing-check-icon {
  color: var(--success);
  flex-shrink: 0;
}

.landing-pricing-card__cta {
  width: 100%;
  justify-content: center;
}

/* ── Footer ──────────────────────────────────────────────────────────────── */
.landing-footer {
  margin-top: auto;
  border-top: 1px solid var(--border-subtle);
  padding: var(--space-6) 0;
}

.landing-footer__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.landing-footer__brand {
  font-size: var(--text-sm);
  font-weight: 500;
}

.landing-footer__links {
  display: flex;
  gap: var(--space-6);
}

.landing-footer__link {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  text-decoration: none;
  transition: color 0.15s var(--ease);
}
.landing-footer__link:hover { color: var(--text-secondary); }

/* ── Responsive ──────────────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .landing-nav,
  .landing-header__actions .landing-btn {
    display: none;
  }

  /* show mode toggle inline on mobile */
  .landing-header__actions {
    display: flex;
  }

  /* hide the two nav buttons but keep mode toggle */
  .landing-header__actions .landing-btn {
    display: none;
  }

  .landing-mobile-menu-btn {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .landing-hero {
    padding: var(--space-10) 0 var(--space-8);
  }

  .landing-values__grid,
  .landing-modules__grid,
  .landing-pricing__grid {
    grid-template-columns: 1fr;
  }

  .landing-footer__inner {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
