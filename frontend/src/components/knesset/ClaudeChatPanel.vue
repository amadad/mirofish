<template>
  <div class="claude-chat-panel" dir="rtl">
    <!-- Header -->
    <div class="ccp-header">
      <div class="ccp-header-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2a10 10 0 0110 10c0 5.52-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2z"/>
          <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
          <line x1="9" y1="9" x2="9.01" y2="9"/>
          <line x1="15" y1="9" x2="15.01" y2="9"/>
        </svg>
      </div>
      <div class="ccp-header-text">
        <span class="ccp-title">Claude ניתוח</span>
        <span class="ccp-subtitle">ניתוח פוליטי חכם בזמן אמת</span>
      </div>
    </div>

    <!-- Quick action chips -->
    <div class="ccp-chips">
      <button
        v-for="chip in quickChips"
        :key="chip.label"
        class="ccp-chip"
        @click="sendQuery(chip.query)"
        :disabled="loading"
      >
        {{ chip.label }}
      </button>
    </div>

    <!-- Messages area -->
    <div class="ccp-messages" ref="messagesContainer">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="ccp-empty">
        <div class="ccp-empty-icon">🔮</div>
        <div class="ccp-empty-text">שאל אותי על הסימולציה, תחזיות, או ניתוח פוליטי</div>
      </div>

      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="ccp-msg"
        :class="msg.from === 'user' ? 'ccp-msg-user' : 'ccp-msg-system'"
      >
        <!-- System avatar -->
        <div v-if="msg.from !== 'user'" class="ccp-avatar-sys">C</div>

        <div
          class="ccp-bubble"
          :class="msg.from === 'user' ? 'ccp-bubble-user' : 'ccp-bubble-system'"
        >
          <div class="ccp-text" v-html="formatText(msg.text)"></div>

          <!-- Vote tally -->
          <div v-if="msg.voteTally && (msg.voteTally.for || msg.voteTally.against)" class="ccp-vote-tally">
            <div class="ccp-vote-bar">
              <div class="ccp-vote-seg ccp-vote-for" :style="{ width: votePercent(msg.voteTally, 'for') + '%' }">
                {{ msg.voteTally.for }} בעד
              </div>
              <div class="ccp-vote-seg ccp-vote-against" :style="{ width: votePercent(msg.voteTally, 'against') + '%' }">
                {{ msg.voteTally.against }} נגד
              </div>
            </div>
          </div>

          <!-- MK references -->
          <div v-if="msg.mks && msg.mks.length" class="ccp-mk-refs">
            <span
              v-for="mk in msg.mks"
              :key="mk.id || mk.name"
              class="ccp-mk-pill"
              @click="$emit('navigate-mk', mk.id)"
            >
              {{ mk.name }} <small v-if="mk.faction">({{ mk.faction }})</small>
            </span>
          </div>
        </div>
      </div>

      <!-- Loading indicator -->
      <div v-if="loading" class="ccp-msg ccp-msg-system">
        <div class="ccp-avatar-sys">C</div>
        <div class="ccp-bubble ccp-bubble-system ccp-loading">
          <span class="ccp-dot"></span>
          <span class="ccp-dot"></span>
          <span class="ccp-dot"></span>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="ccp-input-row">
      <input
        v-model="userInput"
        class="ccp-input"
        placeholder="שאל שאלה..."
        @keydown.enter="sendQuery(userInput)"
        :disabled="loading"
      />
      <button class="ccp-send" @click="sendQuery(userInput)" :disabled="!userInput.trim() || loading">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import { claudeChat } from '../../api/knesset'

const props = defineProps({
  simulationId: { type: String, default: null },
  simulationState: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['navigate-mk'])

const messages = ref([])
const userInput = ref('')
const loading = ref(false)
const sessionId = ref(null)
const messagesContainer = ref(null)

const quickChips = [
  { label: 'סכם את הדיון', query: 'סכם את הדיון הנוכחי בקצרה' },
  { label: 'מי המפתח?', query: 'מי חברי הכנסת המפתחיים בהצבעה הזו ולמה?' },
  { label: 'תחזית סופית', query: 'מה התחזית הסופית שלך להצבעה? מי בעד ומי נגד?' },
  { label: 'נקודות תורפה', query: 'מהן נקודות התורפה של הקואליציה בנושא הזה?' },
]

const sendQuery = async (text) => {
  if (!text || !text.trim() || loading.value) return

  const query = text.trim()
  userInput.value = ''
  messages.value.push({ from: 'user', text: query })
  loading.value = true

  await nextTick()
  scrollToBottom()

  try {
    const res = await claudeChat(query, props.simulationId, sessionId.value, props.simulationState)
    const data = res.data?.data || res.data || {}

    sessionId.value = data.session_id || sessionId.value

    messages.value.push({
      from: 'claude',
      text: data.text || 'לא התקבלה תשובה',
      mks: data.mks || [],
      voteTally: data.voteTally || null,
      bills: data.bills || [],
    })
  } catch (err) {
    messages.value.push({
      from: 'claude',
      text: `שגיאה: ${err.response?.data?.error || err.message}`,
    })
  } finally {
    loading.value = false
    await nextTick()
    scrollToBottom()
  }
}

const scrollToBottom = () => {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

const formatText = (text) => {
  if (!text) return ''
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

const votePercent = (tally, key) => {
  const total = (tally.for || 0) + (tally.against || 0) + (tally.abstain || 0)
  return total > 0 ? Math.round(((tally[key] || 0) / total) * 100) : 0
}
</script>

<style scoped>
.claude-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f0f23;
  border-radius: 12px;
  overflow: hidden;
  font-family: 'Segoe UI', sans-serif;
}

.ccp-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  background: linear-gradient(135deg, #1a1a3e 0%, #2d1b69 100%);
  border-bottom: 1px solid rgba(168, 85, 247, 0.3);
}

.ccp-header-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(168, 85, 247, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #a855f7;
}

.ccp-title { font-weight: 700; color: #e2e8f0; font-size: 15px; }
.ccp-subtitle { font-size: 11px; color: #94a3b8; }
.ccp-header-text { display: flex; flex-direction: column; gap: 2px; }

.ccp-chips {
  display: flex;
  gap: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  flex-shrink: 0;
}

.ccp-chip {
  white-space: nowrap;
  padding: 5px 12px;
  border-radius: 16px;
  border: 1px solid rgba(168, 85, 247, 0.3);
  background: rgba(168, 85, 247, 0.1);
  color: #c4b5fd;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.ccp-chip:hover { background: rgba(168, 85, 247, 0.25); border-color: #a855f7; }
.ccp-chip:disabled { opacity: 0.5; cursor: not-allowed; }

.ccp-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ccp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  opacity: 0.5;
}
.ccp-empty-icon { font-size: 40px; }
.ccp-empty-text { color: #94a3b8; font-size: 14px; text-align: center; }

.ccp-msg { display: flex; gap: 8px; align-items: flex-start; }
.ccp-msg-user { flex-direction: row-reverse; }

.ccp-avatar-sys {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, #7c3aed, #a855f7);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.ccp-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.5;
}

.ccp-bubble-user {
  background: #7c3aed;
  color: white;
  border-bottom-left: 4px;
}

.ccp-bubble-system {
  background: #1e1e3f;
  color: #e2e8f0;
  border: 1px solid rgba(168, 85, 247, 0.15);
}

.ccp-text { word-break: break-word; }
.ccp-text :deep(strong) { color: #c4b5fd; }

.ccp-vote-tally { margin-top: 8px; }
.ccp-vote-bar {
  display: flex;
  border-radius: 6px;
  overflow: hidden;
  height: 24px;
  font-size: 11px;
}
.ccp-vote-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 600;
  min-width: 40px;
}
.ccp-vote-for { background: #22c55e; }
.ccp-vote-against { background: #ef4444; }

.ccp-mk-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.ccp-mk-pill {
  padding: 3px 10px;
  border-radius: 12px;
  background: rgba(168, 85, 247, 0.15);
  color: #c4b5fd;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s;
}
.ccp-mk-pill:hover { background: rgba(168, 85, 247, 0.3); }
.ccp-mk-pill small { opacity: 0.7; }

.ccp-loading {
  display: flex;
  gap: 4px;
  padding: 12px 18px;
}
.ccp-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #a855f7;
  animation: ccp-bounce 1.4s infinite ease-in-out;
}
.ccp-dot:nth-child(1) { animation-delay: 0s; }
.ccp-dot:nth-child(2) { animation-delay: 0.16s; }
.ccp-dot:nth-child(3) { animation-delay: 0.32s; }
@keyframes ccp-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.ccp-input-row {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid rgba(168, 85, 247, 0.2);
  background: #0f0f23;
}

.ccp-input {
  flex: 1;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(168, 85, 247, 0.3);
  background: #1a1a3e;
  color: #e2e8f0;
  font-size: 13px;
  outline: none;
  direction: rtl;
}
.ccp-input:focus { border-color: #a855f7; }
.ccp-input::placeholder { color: #64748b; }

.ccp-send {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  border: none;
  background: #7c3aed;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}
.ccp-send:hover { background: #6d28d9; }
.ccp-send:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
