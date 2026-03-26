<template>
  <div class="analysis-chat-panel" dir="rtl">
    <!-- Header -->
    <div class="acp-header">
      <div class="acp-header-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4M12 8h.01" />
        </svg>
      </div>
      <div class="acp-header-text">
        <span class="acp-title">ניתוח פוליטי</span>
        <span class="acp-subtitle" v-if="stats">
          {{ stats.mks_count }} ח"כים · {{ stats.factions_count }} סיעות · {{ stats.bills_count }} הצעות חוק
        </span>
      </div>
    </div>

    <!-- Quick action chips -->
    <div class="acp-chips">
      <button
        v-for="chip in quickChips"
        :key="chip.label"
        class="acp-chip"
        @click="onChipClick(chip.query)"
      >
        {{ chip.label }}
      </button>
    </div>

    <!-- Messages area -->
    <div class="acp-messages" ref="messagesContainer">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="acp-msg"
        :class="msg.from === 'user' ? 'acp-msg-user' : 'acp-msg-system'"
      >
        <!-- System avatar -->
        <div v-if="msg.from !== 'user'" class="acp-avatar-sys">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>

        <div
          class="acp-bubble"
          :class="msg.from === 'user' ? 'acp-bubble-user' : 'acp-bubble-system'"
        >
          <!-- Plain text -->
          <div v-if="!msg.rich" class="acp-text" v-html="formatText(msg.text)"></div>

          <!-- Rich content: vote tally -->
          <div v-if="msg.voteTally" class="acp-vote-tally">
            <div class="acp-vote-bar">
              <div
                class="acp-vote-seg acp-vote-for"
                :style="{ width: votePercent(msg.voteTally, 'for') + '%' }"
              >
                {{ msg.voteTally.for }} בעד
              </div>
              <div
                class="acp-vote-seg acp-vote-against"
                :style="{ width: votePercent(msg.voteTally, 'against') + '%' }"
              >
                {{ msg.voteTally.against }} נגד
              </div>
              <div
                v-if="msg.voteTally.abstain"
                class="acp-vote-seg acp-vote-abstain"
                :style="{ width: votePercent(msg.voteTally, 'abstain') + '%' }"
              >
                {{ msg.voteTally.abstain }} נמנע
              </div>
            </div>
            <div class="acp-vote-result">
              {{ msg.voteTally.for > msg.voteTally.against ? 'עובר' : 'נדחה' }}
              ({{ msg.voteTally.for }}/{{ msg.voteTally.for + msg.voteTally.against + (msg.voteTally.abstain || 0) }})
            </div>
          </div>

          <!-- Rich content: MK list -->
          <div v-if="msg.mks && msg.mks.length" class="acp-mk-list">
            <div
              v-for="mk in msg.mks"
              :key="mk.id"
              class="acp-mk-card"
              @click="$emit('navigate-mk', mk.id)"
            >
              <div class="acp-mk-card-avatar" :style="{ background: mk.color || '#6b7280' }">
                {{ mkInitials(mk.name) }}
              </div>
              <div class="acp-mk-card-info">
                <span class="acp-mk-card-name">{{ mk.name }}</span>
                <span class="acp-mk-card-faction">{{ mk.faction }}</span>
              </div>
            </div>
          </div>

          <!-- Rich content: bill references -->
          <div v-if="msg.bills && msg.bills.length" class="acp-bill-refs">
            <button
              v-for="bill in msg.bills"
              :key="bill.id"
              class="acp-bill-ref"
              @click="$emit('navigate-bill', bill.id)"
            >
              📜 {{ bill.title }}
            </button>
          </div>
        </div>
      </div>

      <!-- Loading indicator -->
      <div v-if="loading" class="acp-msg acp-msg-system">
        <div class="acp-avatar-sys">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <div class="acp-bubble acp-bubble-system">
          <div class="acp-loading">
            <span>מנתח</span>
            <span class="acp-dots">
              <span class="acp-dot"></span>
              <span class="acp-dot"></span>
              <span class="acp-dot"></span>
            </span>
          </div>
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="messages.length === 0 && !loading" class="acp-empty">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#4b5563" stroke-width="1.5">
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
        <span>שאל שאלה על הכנסת, הצעות חוק, או פוליטיקה ישראלית</span>
      </div>
    </div>

    <!-- Input area -->
    <div class="acp-input-row">
      <input
        v-model="inputText"
        class="acp-input"
        type="text"
        placeholder="שאל שאלה... (לדוגמה: מי יתמוך בהצעת חוק הגיוס?)"
        @keydown.enter="sendQuery"
      />
      <button
        class="acp-send-btn"
        @click="sendQuery"
        :disabled="!inputText.trim() || loading"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 2L11 13" />
          <path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const quickChips = [
  { label: 'מפת כוח', query: 'הצג מפת כוח קואליציה-אופוזיציה' },
  { label: 'ניתוח קואליציה', query: 'נתח את יציבות הקואליציה הנוכחית' },
  { label: 'תחזית הצבעה', query: 'מה התחזית להצבעה הקרובה?' },
  { label: 'השווה תרחישים', query: 'השווה בין תרחישים אפשריים' },
]

const props = defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  stats: { type: Object, default: null },
})

const emit = defineEmits(['send-query', 'navigate-mk', 'navigate-bill'])

const inputText = ref('')
const messagesContainer = ref(null)

function sendQuery() {
  const text = inputText.value.trim()
  if (!text || props.loading) return
  emit('send-query', text)
  inputText.value = ''
}

function onChipClick(query) {
  if (props.loading) return
  emit('send-query', query)
}

function mkInitials(name) {
  if (!name) return '?'
  const parts = name.split(' ')
  if (parts.length >= 2) return parts[0][0] + parts[1][0]
  return parts[0][0]
}

function votePercent(tally, key) {
  const total = (tally.for || 0) + (tally.against || 0) + (tally.abstain || 0)
  if (!total) return 0
  return Math.round(((tally[key] || 0) / total) * 100)
}

function formatText(text) {
  if (!text) return ''
  // Convert **bold** to <strong> and newlines to <br>
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

// Auto-scroll to bottom on new messages or loading change
watch(
  [() => props.messages.length, () => props.loading],
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  }
)
</script>

<style scoped>
.analysis-chat-panel {
  display: flex;
  flex-direction: column;
  background: #0f172a;
  border-radius: 10px;
  height: 100%;
  min-height: 500px;
  overflow: hidden;
  border: 1px solid #1e293b;
}

/* ---- Header ---- */
.acp-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}
.acp-header-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.acp-header-text {
  display: flex;
  flex-direction: column;
}
.acp-title {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
}
.acp-subtitle {
  font-size: 11px;
  color: #94a3b8;
}

/* ---- Quick chips ---- */
.acp-chips {
  display: flex;
  gap: 6px;
  padding: 8px 16px;
  overflow-x: auto;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}
.acp-chip {
  white-space: nowrap;
  padding: 5px 12px;
  border-radius: 16px;
  border: 1px solid #334155;
  background: transparent;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.acp-chip:hover {
  background: #334155;
  color: #e2e8f0;
  border-color: #475569;
}

/* ---- Messages area ---- */
.acp-messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.acp-msg {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.acp-msg-user {
  justify-content: flex-end;
}
.acp-msg-system {
  justify-content: flex-start;
}
.acp-avatar-sys {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: #1e293b;
  border: 1px solid #334155;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  flex-shrink: 0;
  margin-top: 2px;
}

/* ---- Bubbles ---- */
.acp-bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}
.acp-bubble-user {
  background: #2563eb;
  color: #fff;
  border-bottom-left-radius: 4px;
}
.acp-bubble-system {
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-bottom-right-radius: 4px;
}
.acp-text :deep(strong) {
  color: #60a5fa;
  font-weight: 600;
}

/* ---- Vote tally inline ---- */
.acp-vote-tally {
  margin-top: 8px;
}
.acp-vote-bar {
  display: flex;
  height: 24px;
  border-radius: 6px;
  overflow: hidden;
  font-size: 11px;
  font-weight: 600;
}
.acp-vote-seg {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  min-width: 30px;
  padding: 0 6px;
}
.acp-vote-for {
  background: #22c55e;
}
.acp-vote-against {
  background: #ef4444;
}
.acp-vote-abstain {
  background: #eab308;
  color: #1e293b;
}
.acp-vote-result {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  text-align: center;
}

/* ---- MK cards inline ---- */
.acp-mk-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.acp-mk-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 8px;
  background: #0f172a;
  border: 1px solid #334155;
  cursor: pointer;
  transition: border-color 0.15s;
}
.acp-mk-card:hover {
  border-color: #3b82f6;
}
.acp-mk-card-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.acp-mk-card-info {
  display: flex;
  flex-direction: column;
}
.acp-mk-card-name {
  font-size: 11px;
  font-weight: 600;
  color: #e2e8f0;
}
.acp-mk-card-faction {
  font-size: 9px;
  color: #64748b;
}

/* ---- Bill references ---- */
.acp-bill-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}
.acp-bill-ref {
  padding: 4px 10px;
  border-radius: 6px;
  background: #0f172a;
  border: 1px solid #334155;
  color: #60a5fa;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.acp-bill-ref:hover {
  background: #1e3a5f;
  border-color: #3b82f6;
}

/* ---- Loading dots ---- */
.acp-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #94a3b8;
  font-size: 13px;
}
.acp-dots {
  display: flex;
  gap: 3px;
}
.acp-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #64748b;
  animation: acp-bounce 1.2s infinite ease-in-out;
}
.acp-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.acp-dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes acp-bounce {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1.1); }
}

/* ---- Empty state ---- */
.acp-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #475569;
  font-size: 13px;
  text-align: center;
  padding: 20px;
}

/* ---- Input area ---- */
.acp-input-row {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  background: #1e293b;
  border-top: 1px solid #334155;
}
.acp-input {
  flex: 1;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 10px;
  padding: 10px 14px;
  color: #e2e8f0;
  font-size: 13px;
  outline: none;
  direction: rtl;
}
.acp-input::placeholder {
  color: #475569;
}
.acp-input:focus {
  border-color: #2563eb;
}
.acp-send-btn {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: #2563eb;
  border: none;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}
.acp-send-btn:hover:not(:disabled) {
  background: #1d4ed8;
}
.acp-send-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* ---- Scrollbar ---- */
.acp-messages::-webkit-scrollbar {
  width: 5px;
}
.acp-messages::-webkit-scrollbar-track {
  background: transparent;
}
.acp-messages::-webkit-scrollbar-thumb {
  background: #334155;
  border-radius: 3px;
}
</style>
