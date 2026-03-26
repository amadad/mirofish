<template>
  <div class="negotiation-view" dir="rtl">
    <div class="negotiation-grid">
      <!-- Left panel: Offers on table -->
      <div class="offers-panel">
        <h3 class="panel-title">הצעות על השולחן</h3>
        <div v-if="!offersOnTable.length" class="empty-state">אין הצעות פתוחות</div>
        <div
          v-for="offer in offersOnTable"
          :key="offer.offer_id"
          class="offer-card"
        >
          <div class="offer-header">
            <span class="offer-agent">{{ offer.agent_name }}</span>
            <span :class="['status-badge', 'status-' + offer.status]">
              {{ statusBadge(offer.status) }}
            </span>
          </div>
          <p class="offer-terms">{{ offer.terms }}</p>
          <div v-if="offer.conditions" class="offer-conditions">
            <span class="conditions-label">תנאים:</span> {{ offer.conditions }}
          </div>
        </div>
      </div>

      <!-- Right panel: Deal tracker -->
      <div class="deal-panel">
        <h3 class="panel-title">נקודות מוסכמות</h3>
        <div v-if="!Object.keys(dealPoints).length" class="empty-state">טרם הושגו הסכמות</div>
        <div
          v-for="(text, topic) in dealPoints"
          :key="topic"
          class="deal-point"
        >
          <span class="deal-topic">{{ topic }}</span>
          <span class="deal-text">{{ text }}</span>
        </div>
        <div v-if="withdrawnAgents.length" class="withdrawn-section">
          <h4 class="withdrawn-title">פרשו מהמו״מ</h4>
          <span v-for="agent in withdrawnAgents" :key="agent" class="withdrawn-badge">
            🚪 {{ agent }}
          </span>
        </div>
      </div>
    </div>

    <!-- Bottom: Negotiation history -->
    <div class="history-feed">
      <h3 class="panel-title">היסטוריית משא ומתן</h3>
      <div class="history-list">
        <div
          v-for="(entry, idx) in recentHistory"
          :key="idx"
          :class="['history-entry', { 'bluff-alert': entry.detected_bluff }]"
        >
          <span class="history-icon">{{ actionIcon(entry.action_type) }}</span>
          <span class="history-agent">{{ entry.agent_name }}</span>
          <span class="history-text">{{ entry.description }}</span>
          <span v-if="entry.detected_bluff" class="bluff-badge">⚠️ בלוף</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  offersOnTable: { type: Array, default: () => [] },
  dealPoints: { type: Object, default: () => ({}) },
  negotiationHistory: { type: Array, default: () => [] },
  withdrawnAgents: { type: Array, default: () => [] },
})

const recentHistory = computed(() => props.negotiationHistory.slice(-8).reverse())

function statusBadge(status) {
  const map = { open: 'פתוח', accepted: 'התקבל', rejected: 'נדחה' }
  return map[status] || status
}

function actionIcon(type) {
  const map = {
    OFFER: '📋', COUNTER: '↩️', CONCEDE: '🤝',
    BLUFF: '🎭', WALK_AWAY: '🚪', ACCEPT: '✅',
  }
  return map[type] || '•'
}
</script>

<style scoped>
.negotiation-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-family: 'Segoe UI', sans-serif;
}
.negotiation-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.panel-title {
  font-size: 1rem;
  font-weight: 700;
  margin: 0 0 10px;
  color: #1a1a2e;
}
.empty-state {
  color: #888;
  font-style: italic;
  padding: 12px 0;
}
.offer-card {
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 8px;
}
.offer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.offer-agent { font-weight: 600; }
.status-badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}
.status-open { background: #fff3cd; color: #856404; }
.status-accepted { background: #d4edda; color: #155724; }
.status-rejected { background: #f8d7da; color: #721c24; }
.offer-terms { margin: 0; font-size: 0.9rem; }
.offer-conditions { font-size: 0.8rem; color: #555; margin-top: 4px; }
.conditions-label { font-weight: 600; }

.deal-panel { background: #eafaf1; border-radius: 8px; padding: 14px; }
.deal-point {
  display: flex;
  flex-direction: column;
  padding: 6px 0;
  border-bottom: 1px dashed #b2dfdb;
}
.deal-topic { font-weight: 700; color: #2e7d32; font-size: 0.85rem; }
.deal-text { font-size: 0.9rem; color: #333; }
.withdrawn-section { margin-top: 12px; }
.withdrawn-title { font-size: 0.85rem; color: #c62828; margin: 0 0 4px; }
.withdrawn-badge {
  display: inline-block;
  background: #ffebee;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.8rem;
  margin-left: 4px;
}

.history-feed { background: #f5f5f5; border-radius: 8px; padding: 14px; }
.history-list { display: flex; flex-direction: column; gap: 6px; }
.history-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #fff;
  font-size: 0.85rem;
}
.history-entry.bluff-alert {
  background: #fff3e0;
  border: 1px solid #ff9800;
}
.history-icon { font-size: 1.1rem; flex-shrink: 0; }
.history-agent { font-weight: 600; flex-shrink: 0; }
.history-text { color: #555; }
.bluff-badge {
  margin-right: auto;
  background: #ff9800;
  color: #fff;
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 700;
}
</style>
