<template>
  <div class="bill-card" dir="rtl">
    <div class="bill-header">
      <span class="bill-status-badge" :style="statusStyle">{{ statusLabel }}</span>
    </div>

    <h3 class="bill-title">{{ bill.title_he }}</h3>

    <div v-if="bill.sponsor_name" class="bill-sponsor">
      <span class="sponsor-label">מציע:</span>
      <span class="sponsor-name">{{ bill.sponsor_name }}</span>
    </div>

    <!-- Vote bar -->
    <div v-if="bill.votes" class="vote-bar-section">
      <div class="vote-bar">
        <div class="vote-bar-for" :style="{ width: forPct + '%' }" />
        <div class="vote-bar-against" :style="{ width: againstPct + '%' }" />
      </div>
      <div class="vote-bar-labels">
        <span class="vote-for-label">בעד {{ bill.votes.for ?? 0 }}</span>
        <span class="vote-against-label">נגד {{ bill.votes.against ?? 0 }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const STATUS_CONFIG = {
  proposed:  { label: 'הצעה', bg: '#1e40af', color: '#93c5fd' },
  committee: { label: 'ועדה', bg: '#7c3aed', color: '#c4b5fd' },
  reading:   { label: 'קריאה', bg: '#ea580c', color: '#fdba74' },
  passed:    { label: 'אושר', bg: '#16a34a', color: '#86efac' },
  failed:    { label: 'נדחה', bg: '#dc2626', color: '#fca5a5' }
}

const props = defineProps({
  bill: {
    type: Object,
    required: true
  }
})

const cfg = computed(() => STATUS_CONFIG[props.bill.status] ?? STATUS_CONFIG.proposed)
const statusLabel = computed(() => cfg.value.label)
const statusStyle = computed(() => ({
  background: cfg.value.bg + '33',
  color: cfg.value.color,
  borderColor: cfg.value.bg
}))

const forPct = computed(() => {
  const v = props.bill.votes
  if (!v) return 0
  const total = (v.for ?? 0) + (v.against ?? 0)
  return total > 0 ? ((v.for ?? 0) / total) * 100 : 0
})

const againstPct = computed(() => {
  const v = props.bill.votes
  if (!v) return 0
  const total = (v.for ?? 0) + (v.against ?? 0)
  return total > 0 ? ((v.against ?? 0) / total) * 100 : 0
})
</script>

<style scoped>
.bill-card {
  background: #1f2937;
  border-radius: 8px;
  padding: 14px;
  color: #e5e7eb;
  transition: background 0.15s;
}
.bill-card:hover {
  background: #374151;
}
.bill-header {
  margin-bottom: 8px;
}
.bill-status-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 10px;
  border: 1px solid;
}
.bill-title {
  font-size: 15px;
  font-weight: 600;
  color: #f3f4f6;
  margin: 0 0 6px 0;
  line-height: 1.4;
}
.bill-sponsor {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 10px;
}
.sponsor-label {
  color: #6b7280;
}
.sponsor-name {
  color: #d1d5db;
  margin-right: 4px;
}
.vote-bar-section {
  margin-top: 8px;
}
.vote-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: #374151;
}
.vote-bar-for {
  background: #22c55e;
  transition: width 0.4s ease;
}
.vote-bar-against {
  background: #ef4444;
  transition: width 0.4s ease;
}
.vote-bar-labels {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 11px;
}
.vote-for-label { color: #86efac; }
.vote-against-label { color: #fca5a5; }
</style>
