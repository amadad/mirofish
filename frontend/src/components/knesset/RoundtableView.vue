<template>
  <div class="roundtable-view" dir="rtl">
    <h3>שולחן עגול</h3>
    <div class="speakers-ring">
      <div
        v-for="(speaker, i) in speakers"
        :key="speaker.id"
        class="speaker-seat"
        :class="{ active: speaker.id === currentSpeakerId }"
        :style="seatPosition(i, speakers.length)"
      >
        <div class="speaker-avatar">{{ speaker.name.charAt(0) }}</div>
        <div class="speaker-name">{{ speaker.name }}</div>
      </div>
    </div>
    <div class="discussion-feed">
      <div
        v-for="entry in recentEntries"
        :key="entry.id"
        class="feed-entry"
        :class="entry.action_type.toLowerCase()"
      >
        <strong>{{ entry.agent_name }}</strong>
        <span class="action-badge">{{ actionLabel(entry.action_type) }}</span>
        <p>{{ entry.content }}</p>
      </div>
    </div>
    <div v-if="proposals.length" class="proposals-section">
      <h4>הצעות</h4>
      <div v-for="p in proposals" :key="p.id" class="proposal-card">
        <div>{{ p.proposal_text }}</div>
        <div class="supporters">תומכים: {{ p.supporters?.length || 0 }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  speakers: { type: Array, default: () => [] },
  currentSpeakerId: { type: String, default: '' },
  discussionLog: { type: Array, default: () => [] },
  proposals: { type: Array, default: () => [] }
})

const recentEntries = computed(() => {
  return props.discussionLog.slice(-10).reverse()
})

function seatPosition(index, total) {
  const angle = (360 / total) * index - 90
  const rad = (angle * Math.PI) / 180
  const radius = 42
  const x = 50 + radius * Math.cos(rad)
  const y = 50 + radius * Math.sin(rad)
  return {
    position: 'absolute',
    left: `${x}%`,
    top: `${y}%`,
    transform: 'translate(-50%, -50%)'
  }
}

const actionLabels = {
  SPEAK: 'דיבור',
  RESPOND: 'תגובה',
  CHALLENGE: 'אתגור',
  AGREE: 'הסכמה',
  PROPOSE: 'הצעה',
  ABSTAIN: 'נמנע'
}

function actionLabel(type) {
  return actionLabels[type] || type
}
</script>

<style scoped>
.roundtable-view {
  padding: 16px;
}

.roundtable-view h3 {
  margin: 0 0 12px;
  font-size: 18px;
}

.speakers-ring {
  position: relative;
  width: 340px;
  height: 340px;
  margin: 0 auto 24px;
  border: 2px dashed #e0e0e0;
  border-radius: 50%;
}

.speaker-seat {
  text-align: center;
  cursor: default;
  transition: transform 0.2s;
}

.speaker-seat.active {
  transform: translate(-50%, -50%) scale(1.15);
}

.speaker-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #64748b;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  margin: 0 auto 4px;
  border: 2px solid transparent;
  transition: border-color 0.2s, background 0.2s;
}

.speaker-seat.active .speaker-avatar {
  background: #2563eb;
  border-color: #1d4ed8;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.3);
}

.speaker-name {
  font-size: 11px;
  white-space: nowrap;
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Discussion feed */
.discussion-feed {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.feed-entry {
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  border-right: 4px solid #94a3b8;
  font-size: 14px;
}

.feed-entry p {
  margin: 4px 0 0;
  line-height: 1.5;
}

.feed-entry.speak { border-right-color: #2563eb; }
.feed-entry.respond { border-right-color: #16a34a; }
.feed-entry.challenge { border-right-color: #dc2626; }
.feed-entry.agree { border-right-color: #059669; }
.feed-entry.propose { border-right-color: #d97706; }
.feed-entry.abstain { border-right-color: #9ca3af; }

.action-badge {
  display: inline-block;
  margin-right: 8px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  background: #e2e8f0;
  color: #475569;
}

/* Proposals */
.proposals-section h4 {
  margin: 0 0 8px;
  font-size: 16px;
}

.proposal-card {
  padding: 12px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  margin-bottom: 8px;
  background: #fffbeb;
}

.supporters {
  margin-top: 6px;
  font-size: 12px;
  color: #92400e;
}
</style>
