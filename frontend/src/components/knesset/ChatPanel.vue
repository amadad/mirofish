<template>
  <div class="chat-panel" dir="rtl">
    <div class="chat-header">
      <div class="chat-mk-avatar" :style="{ background: factionColor }">
        {{ mkInitials }}
      </div>
      <div class="chat-mk-info">
        <span class="chat-mk-name">{{ mkName }}</span>
        <span class="chat-mk-faction">{{ mkFaction }}</span>
      </div>
    </div>

    <div class="chat-messages" ref="messagesContainer">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="chat-msg"
        :class="msg.from === 'mk' ? 'msg-mk' : 'msg-user'"
      >
        <div v-if="msg.from === 'mk'" class="msg-avatar-sm" :style="{ background: factionColor }">
          {{ mkInitials }}
        </div>
        <div class="msg-bubble" :class="msg.from === 'mk' ? 'bubble-mk' : 'bubble-user'">
          {{ msg.text }}
        </div>
      </div>

      <div v-if="messages.length === 0" class="chat-empty">
        <span>התחל שיחה עם {{ mkName }}</span>
      </div>
    </div>

    <div class="chat-input-row">
      <input
        v-model="inputText"
        class="chat-input"
        type="text"
        placeholder="כתוב הודעה..."
        @keydown.enter="sendMessage"
      />
      <button class="chat-send-btn" @click="sendMessage" :disabled="!inputText.trim()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const FACTION_COLORS = {
  'ליכוד': '#1e40af',
  'הציונות הדתית': '#ea580c',
  'ש"ס': '#0d9488',
  'יהדות התורה': '#1f2937',
  'עוצמה יהודית': '#7c3aed',
  'נועם': '#4b5563',
  'יש עתיד': '#06b6d4',
  'המחנה הממלכתי': '#3b82f6',
  'ישראל ביתנו': '#eab308',
  'העבודה': '#dc2626',
  'מרצ': '#16a34a',
  'חד"ש-תע"ל': '#65a30d',
  'רע"ם': '#059669',
  'בל"ד': '#84cc16',
  'default': '#6b7280'
}

const props = defineProps({
  mkName: { type: String, default: '' },
  mkFaction: { type: String, default: '' },
  messages: { type: Array, default: () => [] }
})

const emit = defineEmits(['send-message'])

const inputText = ref('')
const messagesContainer = ref(null)

const factionColor = computed(() => FACTION_COLORS[props.mkFaction] ?? FACTION_COLORS['default'])

const mkInitials = computed(() => {
  const parts = props.mkName.split(' ')
  if (parts.length >= 2) return parts[0][0] + parts[1][0]
  return (parts[0] || '?')[0]
})

function sendMessage() {
  const text = inputText.value.trim()
  if (!text) return
  emit('send-message', text)
  inputText.value = ''
}

watch(() => props.messages.length, async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
})
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  background: #111827;
  border-radius: 8px;
  height: 100%;
  min-height: 400px;
  overflow: hidden;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: #1f2937;
  border-bottom: 1px solid #374151;
}
.chat-mk-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
  color: #fff;
  flex-shrink: 0;
}
.chat-mk-info {
  display: flex;
  flex-direction: column;
}
.chat-mk-name {
  font-size: 14px;
  font-weight: 600;
  color: #f3f4f6;
}
.chat-mk-faction {
  font-size: 11px;
  color: #9ca3af;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.chat-msg {
  display: flex;
  align-items: flex-end;
  gap: 6px;
}
.msg-mk {
  justify-content: flex-start;
}
.msg-user {
  justify-content: flex-end;
}
.msg-avatar-sm {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.msg-bubble {
  max-width: 75%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}
.bubble-mk {
  background: #1f2937;
  color: #e5e7eb;
  border-bottom-right: 4px;
}
.bubble-user {
  background: #2563eb;
  color: #fff;
  border-bottom-left: 4px;
}
.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  font-size: 13px;
}
.chat-input-row {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  background: #1f2937;
  border-top: 1px solid #374151;
}
.chat-input {
  flex: 1;
  background: #374151;
  border: 1px solid #4b5563;
  border-radius: 8px;
  padding: 8px 12px;
  color: #e5e7eb;
  font-size: 13px;
  outline: none;
  direction: rtl;
}
.chat-input::placeholder {
  color: #6b7280;
}
.chat-input:focus {
  border-color: #3b82f6;
}
.chat-send-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
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
.chat-send-btn:hover:not(:disabled) {
  background: #1d4ed8;
}
.chat-send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
