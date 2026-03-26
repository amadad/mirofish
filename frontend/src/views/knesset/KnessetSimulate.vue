<template>
  <div class="knesset-simulate" dir="rtl">

    <!-- Header -->
    <header class="sim-header">
      <div class="brand" @click="router.push('/')">MIROFISH</div>
      <div class="sim-title" :title="question || 'הדמיית כנסת'">{{ question || 'הדמיית כנסת' }}</div>
      <div class="header-right">
        <span class="status-badge" :class="simStatus">{{ statusLabel }}</span>
        <span class="round-counter">סבב {{ currentRound }}/{{ totalRounds }}</span>
        <button class="btn-close" @click="router.push('/knesset')" aria-label="סגור">✕</button>
      </div>
      <!-- Progress bar embedded at the bottom of the header -->
      <div class="header-progress">
        <div class="header-progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </header>

    <!-- Tab Navigation -->
    <nav class="tab-nav">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <span class="tab-icon">{{ tab.icon }}</span>
        <span class="tab-label">{{ tab.label }}</span>
      </button>
    </nav>

    <!-- Body: Command Center Grid -->
    <div class="cc-body">

      <!-- Stage: dynamic tab component -->
      <div class="cc-stage">
        <!-- Press placeholder -->
        <div v-if="activeTab === 'press'" class="press-placeholder">
          <div class="press-placeholder-inner">
            <span class="press-icon">🎤</span>
            <p class="press-text">פלטפורמת מסיבת העיתונאים — בקרוב</p>
          </div>
        </div>

        <!-- Dynamic component for all other tabs -->
        <component
          v-else-if="currentComponent"
          :is="currentComponent"
          :seats="hemicycleSeats"
          :factionColors="factionColors"
          :simulationId="simId"
          :simulationState="simulationState"
          :actions="feedEvents"
          :tweets="socialTweets"
          :trending="trendingTopics"
          :engagementStats="engagementStats"
          :mks="mksData"
          :pipelineStatus="pipelineStatus"
          @select-mk="onSelectMk"
        />

        <!-- Fallback: no component mapped -->
        <div v-else class="tab-fallback">
          <span class="tab-fallback-text">תוכן הלשונית יופיע כאן</span>
        </div>
      </div>

      <!-- Feed: PlenumFeed (always visible, row 2) -->
      <div class="cc-feed">
        <PlenumFeed
          :actions="feedEvents"
          :isRunning="simStatus === 'running'"
          :simId="simId"
        />
      </div>

      <!-- AI Panel: Claude Chat (spans both rows) -->
      <div class="cc-ai-panel">
        <ClaudeChatPanel
          :simulationId="simId"
          :simulationState="simulationState"
          :selectedMk="selectedMk"
          @navigate-mk="(mkId) => router.push(`/knesset/mk/${mkId}`)"
        />
      </div>

    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { runSimulation, getSimulationStatus } from '../../api/knesset'

import HemicycleChart   from '../../components/knesset/HemicycleChart.vue'
import RoundtableView   from '../../components/knesset/RoundtableView.vue'
import NegotiationView  from '../../components/knesset/NegotiationView.vue'
import BrainstormView   from '../../components/knesset/BrainstormView.vue'
import DecisionView     from '../../components/knesset/DecisionView.vue'
import CoalitionGraph   from '../../components/knesset/CoalitionGraph.vue'
import ClaudeChatPanel  from '../../components/knesset/ClaudeChatPanel.vue'
import PlenumFeed       from '../../components/knesset/PlenumFeed.vue'
import TwitterFeed      from '../../components/knesset/TwitterFeed.vue'
import BackendPanel     from '../../components/knesset/BackendPanel.vue'
import MKBrowser        from '../../components/knesset/MKBrowser.vue'

// ─── Router ────────────────────────────────────────────────────────────────
const route  = useRoute()
const router = useRouter()

// ─── Core state ────────────────────────────────────────────────────────────
const question     = ref(route.query.q || '')
const simId        = ref(route.query.simId || route.params.simId || null)
const simStatus    = ref('pending')   // pending | running | completed | failed
const currentRound = ref(0)
const totalRounds  = ref(5)
const feedEvents   = ref([])
const voteTally    = ref(null)
const activeTab    = ref('plenum')

// ─── Additional state for new components ───────────────────────────────────
const socialTweets    = ref([])
const trendingTopics  = ref([])
const engagementStats = ref({})
const mksData         = ref([])
const pipelineStatus  = ref({
  step:  0,
  steps: ['טעינה', 'אגנטים', 'דיון', 'הצבעה', 'סיכום'],
})
const selectedMk = ref(null)

// ─── Tabs ──────────────────────────────────────────────────────────────────
const tabs = [
  { id: 'plenum',     label: 'מליאה',           icon: '🏛️' },
  { id: 'committee',  label: 'ועדה',             icon: '🪑' },
  { id: 'negotiation',label: 'מו"מ',             icon: '🤝' },
  { id: 'brainstorm', label: 'סיעור',            icon: '💡' },
  { id: 'decision',   label: 'החלטה',            icon: '⚖️' },
  { id: 'press',      label: 'עיתונות',          icon: '🎤' },
  { id: 'twitter',    label: 'טוויטר',           icon: '🐦' },
  { id: 'mks',        label: 'ח"כים',            icon: '👥' },
  { id: 'coalition',  label: 'קואליציה',         icon: '📊' },
  { id: 'backend',    label: 'מאחורי הקלעים',   icon: '⚙️' },
]

// ─── Tab → component map ───────────────────────────────────────────────────
const TAB_COMPONENTS = {
  plenum:      HemicycleChart,
  committee:   RoundtableView,
  negotiation: NegotiationView,
  brainstorm:  BrainstormView,
  decision:    DecisionView,
  press:       null,             // placeholder shown via v-if above
  twitter:     TwitterFeed,
  mks:         MKBrowser,
  coalition:   CoalitionGraph,
  backend:     BackendPanel,
}

const currentComponent = computed(() => TAB_COMPONENTS[activeTab.value] ?? null)

// ─── Factions ──────────────────────────────────────────────────────────────
const FACTIONS = [
  { id: 'likud',          name: 'ליכוד',               color: '#1e40af', seats: 32 },
  { id: 'yesh_atid',      name: 'יש עתיד',             color: '#06b6d4', seats: 24 },
  { id: 'rz',             name: 'הציונות הדתית',       color: '#ea580c', seats: 14 },
  { id: 'shas',           name: 'ש"ס',                  color: '#0d9488', seats: 11 },
  { id: 'utj',            name: 'יהדות התורה',          color: '#374151', seats:  7 },
  { id: 'labor',          name: 'העבודה',               color: '#dc2626', seats:  4 },
  { id: 'meretz',         name: 'מרצ',                  color: '#16a34a', seats:  6 },
  { id: 'arab',           name: 'חד"ש-רע"ם',           color: '#65a30d', seats: 10 },
  { id: 'yib',            name: 'ישראל ביתנו',         color: '#eab308', seats:  6 },
  { id: 'national_unity', name: 'המחנה הממלכתי',      color: '#3b82f6', seats:  6 },
]

const factionColors = computed(() =>
  Object.fromEntries(FACTIONS.map(f => [f.name, f.color]))
)

const hemicycleSeats = computed(() => {
  const seats = []
  for (const f of FACTIONS) {
    for (let i = 0; i < f.seats; i++) {
      seats.push({ faction: f.name, name: `${f.name} ${i + 1}`, mk_id: `${f.id}_${i}` })
    }
  }
  return seats
})

// ─── Computed helpers ──────────────────────────────────────────────────────
const progressPercent = computed(() => {
  if (totalRounds.value === 0) return 0
  return Math.min(100, (currentRound.value / totalRounds.value) * 100)
})

const statusLabel = computed(() => ({
  pending:   'ממתין',
  running:   'פעיל',
  completed: 'הושלם',
  failed:    'שגיאה',
}[simStatus.value] || simStatus.value))

const simulationState = computed(() => ({
  status:        simStatus.value,
  current_round: currentRound.value,
  total_rounds:  totalRounds.value,
  actions:       feedEvents.value,
  vote_tally:    voteTally.value,
}))

// ─── Polling ───────────────────────────────────────────────────────────────
let pollInterval = null

async function pollStatus() {
  if (!simId.value) return
  try {
    const res  = await getSimulationStatus(simId.value)
    const data = res?.data
    if (!data) return

    simStatus.value    = data.status        || simStatus.value
    currentRound.value = data.current_round || currentRound.value
    totalRounds.value  = data.total_rounds  || totalRounds.value

    if (data.events?.length > feedEvents.value.length) {
      feedEvents.value.push(...data.events.slice(feedEvents.value.length))
    }

    if (data.vote_tally) {
      voteTally.value = data.vote_tally
    }

    // Social tweets from backend
    if (data.social_tweets?.length > socialTweets.value.length) {
      socialTweets.value.push(...data.social_tweets.slice(socialTweets.value.length))
    }

    // Pipeline step tracking
    pipelineStatus.value.step = Math.floor((currentRound.value / totalRounds.value) * 5)

    if (data.status === 'completed' || data.status === 'failed') {
      stopPolling()
    }
  } catch (e) {
    console.error('Poll error:', e)
  }
}

function startPolling() {
  pollInterval = setInterval(pollStatus, 2000)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

// ─── MK selection ──────────────────────────────────────────────────────────
function onSelectMk(seat) {
  selectedMk.value = seat
}

// ─── Lifecycle ─────────────────────────────────────────────────────────────
onMounted(async () => {
  if (!simId.value && question.value) {
    try {
      const res = await runSimulation(question.value)
      if (res?.data?.simulation_id) {
        simId.value = res.data.simulation_id
      }
    } catch (e) {
      console.error('Failed to start simulation:', e)
      simStatus.value = 'failed'
      return
    }
  }

  if (simId.value) {
    simStatus.value = 'running'
    startPolling()
    pollStatus()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
/* ── CSS Variables ─────────────────────────────────────────────────────── */
:root,
.knesset-simulate {
  --knesset-bg:          #0C1222;
  --knesset-surface:     #1A2332;
  --knesset-border:      #2A3A4A;
  --knesset-text:        #E2E8F0;
  --knesset-gold:        #C9A84C;
  --knesset-coalition:   #2563EB;
  --knesset-opposition:  #DC2626;
  --knesset-vote-for:    #16A34A;
  --knesset-vote-against:#DC2626;
  --knesset-vote-abstain:#F59E0B;
}

/* ── Root ──────────────────────────────────────────────────────────────── */
.knesset-simulate {
  height: 100vh;
  background: var(--knesset-bg);
  color: var(--knesset-text);
  display: flex;
  flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  overflow: hidden;
}

/* ── Header ────────────────────────────────────────────────────────────── */
.sim-header {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 20px 0;
  background: var(--knesset-surface);
  border-bottom: 1px solid var(--knesset-border);
  flex-shrink: 0;
  min-height: 52px;
}

.brand {
  font-size: 15px;
  font-weight: 800;
  color: var(--knesset-gold);
  cursor: pointer;
  letter-spacing: 2px;
  white-space: nowrap;
  flex-shrink: 0;
  padding-bottom: 10px;
}
.brand:hover {
  opacity: 0.85;
}

.sim-title {
  flex: 1;
  font-size: 14px;
  color: #94A3B8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-bottom: 10px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  padding-bottom: 10px;
}

.status-badge {
  padding: 3px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.status-badge.pending   { background: #374151; color: #9CA3AF; }
.status-badge.running   { background: rgba(201,168,76,0.15); color: var(--knesset-gold); box-shadow: 0 0 8px rgba(201,168,76,0.25); }
.status-badge.completed { background: rgba(22,163,74,0.2); color: #4ADE80; }
.status-badge.failed    { background: rgba(220,38,38,0.2); color: #F87171; }

.round-counter {
  font-size: 12px;
  color: #64748B;
  white-space: nowrap;
}

.btn-close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid var(--knesset-border);
  border-radius: 6px;
  color: #64748B;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}
.btn-close:hover {
  background: rgba(220,38,38,0.15);
  border-color: var(--knesset-opposition);
  color: #F87171;
}

/* Progress bar — thin line at very bottom of header */
.header-progress {
  position: absolute;
  bottom: 0;
  right: 0;
  left: 0;
  height: 2px;
  background: var(--knesset-border);
}
.header-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--knesset-coalition), var(--knesset-gold));
  transition: width 0.5s ease;
}

/* ── Tab Navigation ────────────────────────────────────────────────────── */
.tab-nav {
  display: flex;
  align-items: center;
  overflow-x: auto;
  flex-shrink: 0;
  background: var(--knesset-surface);
  border-bottom: 1px solid var(--knesset-border);
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.tab-nav::-webkit-scrollbar {
  display: none;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #64748B;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.18s;
  flex-shrink: 0;
}
.tab-btn:hover:not(.active) {
  color: var(--knesset-text);
  background: rgba(255,255,255,0.04);
}
.tab-btn.active {
  color: var(--knesset-gold);
  border-bottom-color: var(--knesset-gold);
  background: rgba(201,168,76,0.06);
}

.tab-icon {
  font-size: 14px;
  line-height: 1;
}
.tab-label {
  font-size: 12px;
}

/* ── Body Grid ─────────────────────────────────────────────────────────── */
.cc-body {
  flex: 1;
  display: grid;
  grid-template-columns: 3fr 1fr;
  grid-template-rows: 1fr 180px;
  overflow: hidden;
  min-height: 0;
}

/* Stage: col 1, row 1 */
.cc-stage {
  grid-column: 1;
  grid-row: 1;
  overflow: hidden;
  border-left: 1px solid var(--knesset-border);
  border-bottom: 1px solid var(--knesset-border);
  position: relative;
}

/* Feed: col 1, row 2 */
.cc-feed {
  grid-column: 1;
  grid-row: 2;
  overflow: hidden;
  border-left: 1px solid var(--knesset-border);
}

/* AI Panel: col 2, rows 1–2 */
.cc-ai-panel {
  grid-column: 2;
  grid-row: 1 / 3;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Press Placeholder ─────────────────────────────────────────────────── */
.press-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.press-placeholder-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  opacity: 0.5;
}
.press-icon {
  font-size: 48px;
  line-height: 1;
}
.press-text {
  margin: 0;
  font-size: 16px;
  color: #64748B;
  text-align: center;
}

/* ── Tab Fallback ──────────────────────────────────────────────────────── */
.tab-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.tab-fallback-text {
  font-size: 14px;
  color: #4B5563;
}
</style>
