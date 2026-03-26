<template>
  <div class="backend-panel" dir="rtl">

    <!-- Section 1: Pipeline Status -->
    <div class="panel-section">
      <h3 class="section-title">מצב צינור העיבוד</h3>
      <div class="pipeline-track">
        <div
          v-for="(step, idx) in pipelineStatus.steps"
          :key="idx"
          class="pipeline-step-wrapper"
        >
          <!-- Connector line (before each step except first) -->
          <div
            v-if="idx > 0"
            class="pipeline-connector"
            :class="connectorClass(idx)"
          ></div>

          <div class="pipeline-step" :class="stepClass(idx)">
            <div class="step-node">
              <span v-if="idx < pipelineStatus.step" class="step-icon">✓</span>
              <span v-else-if="idx === pipelineStatus.step" class="step-icon">▶</span>
              <span v-else class="step-icon">○</span>
            </div>
            <span class="step-label">{{ step }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Section 2: Decision Log -->
    <div class="panel-section">
      <h3 class="section-title">יומן פעולות</h3>
      <div v-if="actions.length === 0" class="section-empty">
        אין פעולות עדיין
      </div>
      <div v-else class="table-scroll">
        <table class="action-table">
          <thead>
            <tr>
              <th>סבב</th>
              <th>ח"כ</th>
              <th>פעולה</th>
              <th>תוכן</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(action, idx) in recentActions"
              :key="idx"
              :class="{ 'row-alt': idx % 2 === 1 }"
            >
              <td class="cell-round">{{ action.round ?? '—' }}</td>
              <td class="cell-mk">{{ action.mk_name ?? action.agent_name ?? '—' }}</td>
              <td class="cell-type">
                <span class="action-badge" :class="actionBadgeClass(action.action_type)">
                  {{ action.action_type ?? 'לא ידוע' }}
                </span>
              </td>
              <td class="cell-content">{{ truncate(action.content ?? action.text ?? '', 60) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Section 3: Model Routing -->
    <div class="panel-section">
      <h3 class="section-title">ניתוב מודלים</h3>
      <table class="model-table">
        <thead>
          <tr>
            <th>שכבה</th>
            <th>מודל</th>
            <th>ח"כים</th>
            <th>עלות</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><span class="tier-badge tier-1">Tier 1</span></td>
            <td class="model-name">Claude Sonnet</td>
            <td>השפעה גבוהה</td>
            <td class="cost-cell">$0.003/1K</td>
          </tr>
          <tr class="row-alt">
            <td><span class="tier-badge tier-2">Tier 2</span></td>
            <td class="model-name">Groq Llama 70B</td>
            <td>בינוני</td>
            <td class="cost-cell">$0.001/1K</td>
          </tr>
          <tr>
            <td><span class="tier-badge tier-3">Tier 3</span></td>
            <td class="model-name">Groq Llama 8B</td>
            <td>נמוך</td>
            <td class="cost-cell">$0.0001/1K</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Section 4: Simulation Stats -->
    <div class="panel-section">
      <h3 class="section-title">סטטיסטיקת סימולציה</h3>
      <div class="stats-grid">
        <div class="stat-card">
          <span class="stat-label">סטטוס</span>
          <span class="stat-value status-value" :class="statusClass">
            {{ simulationState.status ?? 'לא פעיל' }}
          </span>
        </div>
        <div class="stat-card">
          <span class="stat-label">סבב נוכחי</span>
          <span class="stat-value">
            {{ simulationState.current_round ?? 0 }} / {{ simulationState.total_rounds ?? 0 }}
          </span>
        </div>
        <div class="stat-card">
          <span class="stat-label">סה"כ פעולות</span>
          <span class="stat-value">{{ actions.length }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">סוגי פעולות</span>
          <span class="stat-value">{{ uniqueActionTypes }}</span>
        </div>
      </div>

      <!-- Action type breakdown -->
      <div v-if="actions.length > 0" class="breakdown">
        <div
          v-for="(count, type) in actionBreakdown"
          :key="type"
          class="breakdown-row"
        >
          <span class="breakdown-type">
            <span class="action-badge" :class="actionBadgeClass(type)">{{ type }}</span>
          </span>
          <div class="breakdown-bar-track">
            <div
              class="breakdown-bar-fill"
              :style="{ width: breakdownPercent(count) + '%' }"
            ></div>
          </div>
          <span class="breakdown-count">{{ count }}</span>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  simulationState: { type: Object, default: () => ({}) },
  pipelineStatus: {
    type: Object,
    default: () => ({
      step: 0,
      steps: ['טעינה', 'אגנטים', 'דיון', 'הצבעה', 'סיכום'],
    }),
  },
  actions: { type: Array, default: () => [] },
})

// Pipeline helpers
function stepClass(idx) {
  if (idx < props.pipelineStatus.step) return 'step-completed'
  if (idx === props.pipelineStatus.step) return 'step-current'
  return 'step-pending'
}

function connectorClass(idx) {
  if (idx <= props.pipelineStatus.step) return 'connector-active'
  return 'connector-inactive'
}

// Actions — last 20
const recentActions = computed(() => props.actions.slice(-20).reverse())

// Action breakdown counts
const actionBreakdown = computed(() => {
  const counts = {}
  for (const a of props.actions) {
    const t = a.action_type ?? 'לא ידוע'
    counts[t] = (counts[t] ?? 0) + 1
  }
  return counts
})

const uniqueActionTypes = computed(() => Object.keys(actionBreakdown.value).length)

function breakdownPercent(count) {
  const max = Math.max(...Object.values(actionBreakdown.value), 1)
  return Math.round((count / max) * 100)
}

// Status class
const statusClass = computed(() => {
  const s = props.simulationState.status
  if (!s) return ''
  if (s === 'running') return 'status-running'
  if (s === 'completed' || s === 'done') return 'status-done'
  if (s === 'error') return 'status-error'
  return ''
})

// Action badge class
function actionBadgeClass(type) {
  if (!type) return 'badge-default'
  const t = type.toLowerCase()
  if (t.includes('speak') || t.includes('דיבור')) return 'badge-speak'
  if (t.includes('vote') || t.includes('הצב')) return 'badge-vote'
  if (t.includes('tweet') || t.includes('ציו')) return 'badge-tweet'
  if (t.includes('nego') || t.includes('משא')) return 'badge-nego'
  return 'badge-default'
}

function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '…' : str
}
</script>

<style scoped>
.backend-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 2px;
  color: var(--knesset-text, #E2E8F0);
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  font-size: 0.85rem;
}

/* Section Card */
.panel-section {
  background: var(--knesset-surface, #1A2332);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 10px;
  padding: 14px 16px;
}

.section-title {
  margin: 0 0 12px 0;
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--knesset-gold, #C9A84C);
  border-bottom: 1px solid var(--knesset-border, #2A3A4A);
  padding-bottom: 8px;
}

.section-empty {
  color: #6B7280;
  font-size: 0.8rem;
  padding: 8px 0;
}

/* ── Pipeline ── */
.pipeline-track {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding: 4px 0 8px;
  gap: 0;
}

.pipeline-step-wrapper {
  display: flex;
  align-items: center;
}

.pipeline-connector {
  height: 2px;
  width: 24px;
  flex-shrink: 0;
  margin: 0 4px;
  border-radius: 1px;
  transition: background 0.3s ease;
}

.connector-active {
  background: #22c55e;
}

.connector-inactive {
  background: #2A3A4A;
}

.pipeline-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 52px;
}

.step-node {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  transition: background 0.3s ease, border-color 0.3s ease;
  border: 2px solid;
}

.step-completed .step-node {
  background: rgba(34, 197, 94, 0.15);
  border-color: #22c55e;
  color: #22c55e;
}

.step-current .step-node {
  background: rgba(201, 168, 76, 0.2);
  border-color: var(--knesset-gold, #C9A84C);
  color: var(--knesset-gold, #C9A84C);
  box-shadow: 0 0 8px rgba(201, 168, 76, 0.3);
}

.step-pending .step-node {
  background: transparent;
  border-color: #374151;
  color: #6B7280;
}

.step-label {
  font-size: 0.65rem;
  color: #9CA3AF;
  white-space: nowrap;
  text-align: center;
}

.step-completed .step-label { color: #22c55e; }
.step-current .step-label { color: var(--knesset-gold, #C9A84C); font-weight: 600; }

/* ── Tables ── */
.table-scroll {
  overflow-x: auto;
  max-height: 260px;
  overflow-y: auto;
}

.action-table,
.model-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
}

.action-table th,
.model-table th {
  text-align: right;
  padding: 6px 8px;
  color: #9CA3AF;
  font-weight: 600;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--knesset-border, #2A3A4A);
  position: sticky;
  top: 0;
  background: var(--knesset-surface, #1A2332);
}

.action-table td,
.model-table td {
  padding: 6px 8px;
  color: var(--knesset-text, #E2E8F0);
  vertical-align: middle;
  border-bottom: 1px solid rgba(42, 58, 74, 0.4);
}

.row-alt {
  background: rgba(255, 255, 255, 0.025);
}

.cell-round {
  color: var(--knesset-gold, #C9A84C);
  font-weight: 600;
  white-space: nowrap;
}

.cell-mk {
  white-space: nowrap;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-type {
  white-space: nowrap;
}

.cell-content {
  color: #9CA3AF;
  font-size: 0.75rem;
  max-width: 200px;
}

.model-name {
  font-weight: 600;
  direction: ltr;
  text-align: right;
}

.cost-cell {
  color: var(--knesset-gold, #C9A84C);
  font-family: monospace;
  font-size: 0.75rem;
  direction: ltr;
  text-align: right;
}

/* ── Action badges ── */
.action-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 20px;
  font-size: 0.68rem;
  font-weight: 600;
  white-space: nowrap;
}

.badge-speak  { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; }
.badge-vote   { background: rgba(34, 197, 94, 0.2);  color: #86efac; }
.badge-tweet  { background: rgba(6, 182, 212, 0.2);  color: #67e8f9; }
.badge-nego   { background: rgba(234, 88, 12, 0.2);  color: #fdba74; }
.badge-default { background: rgba(107, 114, 128, 0.2); color: #9CA3AF; }

.tier-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 0.68rem;
  font-weight: 700;
  direction: ltr;
}

.tier-1 { background: rgba(201, 168, 76, 0.2); color: var(--knesset-gold, #C9A84C); }
.tier-2 { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; }
.tier-3 { background: rgba(107, 114, 128, 0.2); color: #9CA3AF; }

/* ── Stats Grid ── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.stat-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-label {
  font-size: 0.7rem;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.stat-value {
  font-size: 1rem;
  font-weight: 700;
  color: var(--knesset-text, #E2E8F0);
}

.status-running { color: #22c55e; }
.status-done    { color: var(--knesset-gold, #C9A84C); }
.status-error   { color: #ef4444; }

/* ── Breakdown ── */
.breakdown {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.breakdown-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.breakdown-type {
  min-width: 80px;
  flex-shrink: 0;
}

.breakdown-bar-track {
  flex: 1;
  height: 6px;
  background: rgba(42, 58, 74, 0.8);
  border-radius: 3px;
  overflow: hidden;
}

.breakdown-bar-fill {
  height: 100%;
  background: var(--knesset-gold, #C9A84C);
  border-radius: 3px;
  transition: width 0.4s ease;
}

.breakdown-count {
  min-width: 24px;
  text-align: left;
  font-size: 0.75rem;
  color: #9CA3AF;
}

/* Scrollbars */
.table-scroll::-webkit-scrollbar { width: 4px; height: 4px; }
.table-scroll::-webkit-scrollbar-track { background: transparent; }
.table-scroll::-webkit-scrollbar-thumb { background: #2A3A4A; border-radius: 2px; }
.pipeline-track::-webkit-scrollbar { height: 3px; }
.pipeline-track::-webkit-scrollbar-thumb { background: #2A3A4A; border-radius: 2px; }
</style>
