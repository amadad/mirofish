<template>
  <div class="plenum-feed" dir="rtl">
    <div class="feed-header">
      <span class="feed-title">פעולות מליאה</span>
      <span v-if="actions.length" class="feed-count">{{ actions.length }}</span>
    </div>

    <!-- Event injection bar (visible only during active simulation) -->
    <div class="inject-bar" v-if="isRunning">
      <input
        v-model="injectText"
        class="inject-input"
        placeholder="הזרק אירוע חי לסימולציה..."
        @keydown.enter="doInject"
      />
      <button class="inject-btn" @click="doInject" :disabled="!injectText.trim() || injecting">
        <span v-if="injecting" class="inject-spinner"></span>
        <span v-else>⚡ הזרק</span>
      </button>
    </div>

    <div class="feed-list" ref="feedList">
      <div
        v-for="(action, i) in sortedActions"
        :key="i"
        class="feed-item"
      >
        <div class="feed-icon" :style="{ background: iconBg(action.action_type) }">
          <span v-html="actionIcon(action.action_type)" />
        </div>
        <div class="feed-content">
          <div class="feed-top-row">
            <span class="feed-mk-name">{{ action.mk_name }}</span>
            <span class="feed-action-type">{{ actionLabel(action.action_type) }}</span>
          </div>
          <p class="feed-text">{{ action.content_he }}</p>
          <div class="feed-meta">
            <span v-if="action.round_num" class="feed-round">סבב {{ action.round_num }}</span>
            <span v-if="action.timestamp" class="feed-time">{{ formatTime(action.timestamp) }}</span>
          </div>
        </div>
      </div>

      <div v-if="!actions.length" class="feed-empty">
        <span>אין פעולות עדיין</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { injectLiveEvent } from '../../api/knesset'

const props = defineProps({
  actions: {
    type: Array,
    default: () => []
  },
  isRunning: {
    type: Boolean,
    default: false
  },
  simId: {
    type: String,
    default: null
  },
})

const injectText = ref('')
const injecting = ref(false)

async function doInject() {
  if (!injectText.value.trim() || injecting.value) return
  injecting.value = true
  try {
    await injectLiveEvent(injectText.value.trim(), '', 'manual', 'high')
    injectText.value = ''
  } catch (e) {
    console.error('Inject failed:', e)
  } finally {
    injecting.value = false
  }
}

const feedList = ref(null)

const sortedActions = computed(() => {
  return [...props.actions].reverse()
})

const ACTION_CONFIG = {
  VOTE:    { label: 'הצבעה',  icon: '&#x1F5F3;', bg: '#1e40af' },
  SPEAK:   { label: 'נאום',   icon: '&#x1F4E2;', bg: '#7c3aed' },
  PROPOSE: { label: 'הצעה',   icon: '&#x1F4DC;', bg: '#ea580c' },
  LOBBY:   { label: 'שדלנות', icon: '&#x1F91D;', bg: '#059669' }
}

function actionIcon(type) {
  return ACTION_CONFIG[type]?.icon ?? '&#x25CF;'
}
function actionLabel(type) {
  return ACTION_CONFIG[type]?.label ?? type
}
function iconBg(type) {
  return (ACTION_CONFIG[type]?.bg ?? '#6b7280') + '44'
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })
}

watch(() => props.actions.length, async () => {
  await nextTick()
  if (feedList.value) {
    feedList.value.scrollTop = 0
  }
})
</script>

<style scoped>
.plenum-feed {
  background: #111827;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
}
.feed-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  background: #1f2937;
  border-bottom: 1px solid #374151;
}
.feed-title {
  font-size: 14px;
  font-weight: 600;
  color: #f3f4f6;
}
.feed-count {
  font-size: 11px;
  background: #374151;
  color: #9ca3af;
  padding: 1px 8px;
  border-radius: 10px;
}
.feed-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.feed-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  background: #1f2937;
  border-radius: 6px;
  transition: background 0.15s;
}
.feed-item:hover {
  background: #374151;
}
.feed-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.feed-content {
  flex: 1;
  min-width: 0;
}
.feed-top-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}
.feed-mk-name {
  font-size: 13px;
  font-weight: 600;
  color: #f3f4f6;
}
.feed-action-type {
  font-size: 10px;
  color: #9ca3af;
  background: #374151;
  padding: 1px 6px;
  border-radius: 8px;
}
.feed-text {
  font-size: 12px;
  color: #d1d5db;
  margin: 0;
  line-height: 1.5;
}
.feed-meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
.feed-round,
.feed-time {
  font-size: 10px;
  color: #6b7280;
}
.feed-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  font-size: 13px;
}

/* Inject bar */
.inject-bar {
  display: flex;
  gap: 8px;
  padding: 8px;
  background: #1A2332;
  border-bottom: 1px solid #2A3A4A;
  flex-shrink: 0;
}
.inject-input {
  flex: 1;
  padding: 7px 12px;
  background: #0C1222;
  border: 1px solid #2A3A4A;
  border-radius: 6px;
  color: #E2E8F0;
  font-size: 12px;
  outline: none;
  text-align: right;
}
.inject-input:focus {
  border-color: #C9A84C;
}
.inject-input::placeholder {
  color: #4b5563;
}
.inject-btn {
  padding: 7px 14px;
  background: #C9A84C;
  color: #0C1222;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}
.inject-btn:hover:not(:disabled) {
  background: #b8933a;
}
.inject-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.inject-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid #0C1222;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
