<template>
  <div class="knesset-results" dir="rtl">
    <!-- Header -->
    <header class="results-header">
      <div class="brand" @click="$router.push('/')">MIROFISH</div>
      <div class="header-center">
        <h2 class="results-title">{{ simulation?.question_he || 'תוצאות הדמיה' }}</h2>
      </div>
      <div class="header-controls">
        <button class="btn-outline" @click="$router.push('/knesset')">הדמיה חדשה</button>
        <button class="btn-outline" @click="$router.push('/knesset')">חזרה</button>
      </div>
    </header>

    <div class="loading-state" v-if="loading">
      <div class="spinner"></div>
      <span>טוען תוצאות...</span>
    </div>

    <main class="results-main" v-else-if="simulation">
      <!-- Outcome Banner -->
      <section class="outcome-banner" :class="simulation.passed ? 'passed' : 'failed'">
        <div class="outcome-icon">{{ simulation.passed ? '✅' : '❌' }}</div>
        <div class="outcome-text">
          <h1 class="outcome-title">{{ simulation.passed ? 'הצעת החוק אושרה' : 'הצעת החוק נדחתה' }}</h1>
          <div class="outcome-votes">
            <span class="vote-for">בעד: {{ simulation.votes_for }}</span>
            <span class="vote-against">נגד: {{ simulation.votes_against }}</span>
            <span class="vote-abstain">נמנעים: {{ simulation.votes_abstain }}</span>
          </div>
        </div>
      </section>

      <!-- Vote Breakdown by Faction -->
      <section class="section">
        <h3 class="section-title">פילוח הצבעה לפי סיעה</h3>
        <div class="faction-chart">
          <div v-for="f in factionBreakdown" :key="f.name" class="faction-row">
            <div class="faction-info">
              <span class="faction-dot" :style="{ background: f.color }"></span>
              <span class="faction-name">{{ f.name }}</span>
              <span class="faction-seats">({{ f.seats }})</span>
            </div>
            <div class="faction-bar-container">
              <div class="faction-bar-bg">
                <div class="faction-bar for" :style="{ width: barWidth(f.for, f.seats) }"></div>
                <div class="faction-bar against" :style="{ width: barWidth(f.against, f.seats), right: 0 }"></div>
              </div>
              <div class="faction-counts">
                <span class="count-for">{{ f.for }}</span>
                <span class="count-against">{{ f.against }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Key Arguments -->
      <section class="section" v-if="keyArguments.length">
        <h3 class="section-title">טיעונים מרכזיים</h3>
        <div class="arguments-list">
          <div
            v-for="(arg, i) in keyArguments"
            :key="i"
            class="argument-card"
            :class="arg.side"
          >
            <div class="arg-header" @click="arg.expanded = !arg.expanded">
              <span class="arg-side-badge" :class="arg.side">{{ arg.side === 'for' ? 'בעד' : 'נגד' }}</span>
              <span class="arg-speaker">{{ arg.speaker }}</span>
              <span class="arg-faction">({{ arg.faction }})</span>
              <span class="arg-toggle">{{ arg.expanded ? '▲' : '▼' }}</span>
            </div>
            <div class="arg-body" v-if="arg.expanded">
              <p>{{ arg.text }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- Swing MKs -->
      <section class="section" v-if="swingMKs.length">
        <h3 class="section-title">ח"כים מתנדנדים</h3>
        <p class="section-desc">ח"כים שהצבעתם הייתה מפתיעה או שונה מעמדת הסיעה</p>
        <div class="swing-grid">
          <div v-for="mk in swingMKs" :key="mk.id" class="swing-card" @click="$router.push(`/knesset/mk/${mk.id}`)">
            <div class="swing-avatar">{{ mk.name?.charAt(0) }}</div>
            <div class="swing-info">
              <div class="swing-name">{{ mk.name }}</div>
              <div class="swing-faction" :style="{ color: mk.factionColor }">{{ mk.faction }}</div>
              <div class="swing-reason">{{ mk.reason }}</div>
            </div>
            <span class="swing-vote" :class="mk.vote">{{ mk.vote === 'for' ? 'בעד' : 'נגד' }}</span>
          </div>
        </div>
      </section>

      <!-- What Would It Take -->
      <section class="section" v-if="whatWouldItTake">
        <h3 class="section-title">מה היה צריך כדי לשנות את התוצאה?</h3>
        <div class="analysis-card">
          <p>{{ whatWouldItTake }}</p>
        </div>
      </section>
    </main>

    <div class="error-state" v-else>
      <p>לא נמצאו תוצאות</p>
      <button class="btn-outline" @click="$router.push('/knesset')">חזרה</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSimulationStatus } from '../../api/knesset'

const route = useRoute()
const router = useRouter()

const simId = ref(route.params.simId)
const loading = ref(true)
const simulation = ref(null)
const factionBreakdown = ref([])
const keyArguments = ref([])
const swingMKs = ref([])
const whatWouldItTake = ref('')

const factionColors = {
  'הליכוד': '#3b82f6',
  'יש עתיד': '#06b6d4',
  'הציונות הדתית': '#f97316',
  'ש"ס': '#14b8a6',
  'יהדות התורה': '#6b7280',
  'העבודה': '#ef4444',
  'מרצ': '#22c55e',
  'רע"ם/חד"ש': '#84cc16',
  'ישראל ביתנו': '#8b5cf6',
  'המחנה הממלכתי': '#0ea5e9'
}

function barWidth(count, total) {
  if (!total) return '0%'
  return (count / total * 100) + '%'
}

onMounted(async () => {
  try {
    const res = await getSimulationStatus(simId.value)
    if (res?.data) {
      const d = res.data

      simulation.value = {
        question_he: d.question_he || '',
        passed: d.result?.passed ?? false,
        votes_for: d.result?.votes_for ?? 0,
        votes_against: d.result?.votes_against ?? 0,
        votes_abstain: d.result?.votes_abstain ?? 0
      }

      // Faction breakdown
      if (d.result?.faction_breakdown) {
        factionBreakdown.value = d.result.faction_breakdown.map(f => ({
          ...f,
          color: factionColors[f.name] || '#6b7280'
        }))
      }

      // Key arguments
      if (d.result?.key_arguments) {
        keyArguments.value = d.result.key_arguments.map(a => ({ ...a, expanded: false }))
      }

      // Swing MKs
      if (d.result?.swing_mks) {
        swingMKs.value = d.result.swing_mks.map(mk => ({
          ...mk,
          factionColor: factionColors[mk.faction] || '#6b7280'
        }))
      }

      // What would it take
      if (d.result?.what_would_it_take) {
        whatWouldItTake.value = d.result.what_would_it_take
      }
    }
  } catch (e) {
    console.error('Failed to load results:', e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.knesset-results {
  min-height: 100vh;
  background: #0f1117;
  color: #e5e7eb;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

/* Header */
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  border-bottom: 1px solid #1f2937;
}
.brand {
  font-size: 16px;
  font-weight: 700;
  color: #60a5fa;
  cursor: pointer;
  letter-spacing: 2px;
}
.results-title {
  font-size: 15px;
  color: #9ca3af;
  margin: 0;
  font-weight: 400;
}
.header-controls {
  display: flex;
  gap: 8px;
}
.btn-outline {
  padding: 6px 16px;
  background: transparent;
  border: 1px solid #374151;
  border-radius: 6px;
  color: #9ca3af;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-outline:hover {
  background: #1f2937;
  color: #e5e7eb;
}

/* Main */
.results-main {
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px 64px;
}

/* Loading */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 120px 0;
  color: #6b7280;
  font-size: 16px;
}
.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid #374151;
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Error */
.error-state {
  text-align: center;
  padding: 120px 0;
  color: #6b7280;
}

/* Outcome Banner */
.outcome-banner {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 24px 32px;
  border-radius: 12px;
  margin-bottom: 32px;
}
.outcome-banner.passed {
  background: linear-gradient(135deg, #064e3b, #0f1117);
  border: 1px solid #065f46;
}
.outcome-banner.failed {
  background: linear-gradient(135deg, #7f1d1d, #0f1117);
  border: 1px solid #991b1b;
}
.outcome-icon {
  font-size: 36px;
}
.outcome-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 8px;
}
.outcome-votes {
  display: flex;
  gap: 16px;
  font-size: 14px;
}
.vote-for { color: #6ee7b7; }
.vote-against { color: #fca5a5; }
.vote-abstain { color: #9ca3af; }

/* Section */
.section {
  margin-bottom: 32px;
}
.section-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 16px;
}
.section-desc {
  font-size: 13px;
  color: #6b7280;
  margin: -8px 0 16px;
}

/* Faction Chart */
.faction-chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.faction-row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.faction-info {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 200px;
  flex-shrink: 0;
}
.faction-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.faction-name {
  font-size: 13px;
  font-weight: 500;
}
.faction-seats {
  font-size: 11px;
  color: #6b7280;
}
.faction-bar-container {
  flex: 1;
  position: relative;
}
.faction-bar-bg {
  height: 20px;
  background: #1f2937;
  border-radius: 4px;
  position: relative;
  overflow: hidden;
}
.faction-bar {
  position: absolute;
  top: 0;
  height: 100%;
  transition: width 0.5s ease;
}
.faction-bar.for {
  right: 0;
  background: #22c55e;
  border-radius: 4px 0 0 4px;
}
.faction-bar.against {
  left: 0;
  background: #ef4444;
  border-radius: 0 4px 4px 0;
}
.faction-counts {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-top: 2px;
}
.count-for { color: #6ee7b7; }
.count-against { color: #fca5a5; }

/* Arguments */
.arguments-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.argument-card {
  background: #1a1d27;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #1f2937;
}
.arg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.2s;
}
.arg-header:hover {
  background: #1f2937;
}
.arg-side-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.arg-side-badge.for { background: #064e3b; color: #6ee7b7; }
.arg-side-badge.against { background: #7f1d1d; color: #fca5a5; }
.arg-speaker {
  font-weight: 500;
  font-size: 14px;
}
.arg-faction {
  font-size: 12px;
  color: #6b7280;
}
.arg-toggle {
  margin-right: auto;
  font-size: 10px;
  color: #6b7280;
}
.arg-body {
  padding: 0 16px 16px;
  font-size: 14px;
  color: #d1d5db;
  line-height: 1.7;
}
.arg-body p {
  margin: 0;
}

/* Swing MKs */
.swing-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
}
.swing-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: #1a1d27;
  border: 1px solid #1f2937;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s;
}
.swing-card:hover {
  border-color: #374151;
}
.swing-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #374151;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: #e5e7eb;
  flex-shrink: 0;
}
.swing-info {
  flex: 1;
  min-width: 0;
}
.swing-name {
  font-size: 14px;
  font-weight: 600;
}
.swing-faction {
  font-size: 12px;
}
.swing-reason {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
}
.swing-vote {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}
.swing-vote.for { background: #064e3b; color: #6ee7b7; }
.swing-vote.against { background: #7f1d1d; color: #fca5a5; }

/* Analysis Card */
.analysis-card {
  padding: 20px 24px;
  background: #1a1d27;
  border: 1px solid #1f2937;
  border-radius: 10px;
  font-size: 15px;
  line-height: 1.8;
  color: #d1d5db;
}
.analysis-card p {
  margin: 0;
}
</style>
