<template>
  <div class="mk-detail" dir="rtl">
    <!-- Header -->
    <header class="mk-header">
      <div class="brand" @click="$router.push('/')">MIROFISH</div>
      <div class="header-controls">
        <button class="btn-outline" @click="$router.back()">חזרה</button>
      </div>
    </header>

    <div class="loading-state" v-if="loading">
      <div class="spinner"></div>
      <span>טוען פרופיל...</span>
    </div>

    <main class="mk-main" v-else-if="mk">
      <!-- Profile Header -->
      <section class="profile-section">
        <div class="profile-avatar">
          <span>{{ mk.name?.charAt(0) }}</span>
        </div>
        <div class="profile-info">
          <h1 class="profile-name">{{ mk.name }}</h1>
          <div class="profile-faction" :style="{ color: factionColor }">{{ mk.faction }}</div>
          <div class="profile-tags" v-if="mk.ideology_tags?.length">
            <span v-for="tag in mk.ideology_tags" :key="tag" class="tag">{{ tag }}</span>
          </div>
        </div>
        <button class="btn-chat" @click="showChat = true">
          💬 שוחח עם הח"כ
        </button>
      </section>

      <!-- Stances -->
      <section class="section" v-if="mk.stances?.length">
        <h3 class="section-title">עמדות</h3>
        <table class="stances-table">
          <thead>
            <tr>
              <th>נושא</th>
              <th>עמדה</th>
              <th>עוצמה</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in mk.stances" :key="i">
              <td>{{ s.topic }}</td>
              <td>
                <span class="stance-badge" :class="stanceClass(s.position)">{{ s.position }}</span>
              </td>
              <td>
                <div class="strength-bar">
                  <div class="strength-fill" :style="{ width: (s.strength || 50) + '%' }"></div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Voting History -->
      <section class="section" v-if="mk.voting_history?.length">
        <h3 class="section-title">היסטוריית הצבעות</h3>
        <div class="vote-history-list">
          <div v-for="(v, i) in mk.voting_history" :key="i" class="vote-history-item">
            <div class="vh-question">{{ v.question_he }}</div>
            <div class="vh-meta">
              <span class="vh-vote" :class="v.vote">{{ voteLabel(v.vote) }}</span>
              <span class="vh-date">{{ v.date }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Memory Summary -->
      <section class="section" v-if="mk.memory_summary">
        <h3 class="section-title">סיכום זיכרון (מהדמיות קודמות)</h3>
        <div class="memory-card">
          <p>{{ mk.memory_summary }}</p>
        </div>
      </section>
    </main>

    <div class="error-state" v-else>
      <p>לא נמצא ח"כ</p>
      <button class="btn-outline" @click="$router.push('/knesset')">חזרה</button>
    </div>

    <!-- Chat Modal -->
    <div class="chat-overlay" v-if="showChat" @click.self="showChat = false">
      <div class="chat-modal">
        <div class="chat-header">
          <h3>שיחה עם {{ mk?.name }}</h3>
          <button class="chat-close" @click="showChat = false">✕</button>
        </div>
        <div class="chat-messages" ref="chatMsgsEl">
          <div v-for="(msg, i) in chatMessages" :key="i" class="chat-msg" :class="msg.role">
            <div class="msg-text">{{ msg.text }}</div>
          </div>
          <div v-if="chatLoading" class="chat-msg mk">
            <div class="msg-text typing">
              <span class="dot-1">.</span><span class="dot-2">.</span><span class="dot-3">.</span>
            </div>
          </div>
        </div>
        <div class="chat-input-row">
          <input
            v-model="chatInput"
            type="text"
            class="chat-input"
            placeholder="כתוב הודעה..."
            @keydown.enter="sendChat"
          />
          <button class="chat-send" @click="sendChat" :disabled="!chatInput.trim() || chatLoading">שלח</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { getMKDetail, chatWithMK } from '../../api/knesset'

const route = useRoute()
const mkId = ref(route.params.mkId)
const loading = ref(true)
const mk = ref(null)
const showChat = ref(false)
const chatInput = ref('')
const chatMessages = ref([])
const chatLoading = ref(false)
const chatMsgsEl = ref(null)

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

const factionColor = ref('#6b7280')

function stanceClass(position) {
  if (!position) return ''
  const p = position.toLowerCase()
  if (p.includes('בעד') || p.includes('תומך')) return 'positive'
  if (p.includes('נגד') || p.includes('מתנגד')) return 'negative'
  return 'neutral'
}

function voteLabel(v) {
  const map = { for: 'בעד', against: 'נגד', abstain: 'נמנע' }
  return map[v] || v
}

onMounted(async () => {
  try {
    const res = await getMKDetail(mkId.value)
    if (res?.data) {
      mk.value = res.data
      factionColor.value = factionColors[res.data.faction] || '#6b7280'
    }
  } catch (e) {
    console.error('Failed to load MK:', e)
  } finally {
    loading.value = false
  }
})

async function sendChat() {
  if (!chatInput.value.trim() || chatLoading.value) return
  const msg = chatInput.value.trim()
  chatMessages.value.push({ role: 'user', text: msg })
  chatInput.value = ''
  chatLoading.value = true

  nextTick(() => {
    if (chatMsgsEl.value) chatMsgsEl.value.scrollTop = chatMsgsEl.value.scrollHeight
  })

  try {
    const res = await chatWithMK([mkId.value], msg)
    if (res?.data?.responses?.length) {
      chatMessages.value.push({ role: 'mk', text: res.data.responses[0].text })
    } else {
      chatMessages.value.push({ role: 'mk', text: 'לא הצלחתי להשיב. נסה שוב.' })
    }
  } catch (e) {
    chatMessages.value.push({ role: 'mk', text: 'שגיאה בתקשורת. נסה שוב.' })
  } finally {
    chatLoading.value = false
    nextTick(() => {
      if (chatMsgsEl.value) chatMsgsEl.value.scrollTop = chatMsgsEl.value.scrollHeight
    })
  }
}
</script>

<style scoped>
.mk-detail {
  min-height: 100vh;
  background: #0f1117;
  color: #e5e7eb;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

/* Header */
.mk-header {
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
.btn-outline {
  padding: 6px 16px;
  background: transparent;
  border: 1px solid #374151;
  border-radius: 6px;
  color: #9ca3af;
  font-size: 13px;
  cursor: pointer;
}
.btn-outline:hover {
  background: #1f2937;
  color: #e5e7eb;
}

/* Loading / Error */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 120px 0;
  color: #6b7280;
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
.error-state {
  text-align: center;
  padding: 120px 0;
  color: #6b7280;
}

/* Main */
.mk-main {
  max-width: 800px;
  margin: 0 auto;
  padding: 32px 24px 64px;
}

/* Profile */
.profile-section {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 40px;
  flex-wrap: wrap;
}
.profile-avatar {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: #1f2937;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: 700;
  flex-shrink: 0;
}
.profile-info {
  flex: 1;
  min-width: 0;
}
.profile-name {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 4px;
}
.profile-faction {
  font-size: 16px;
  font-weight: 500;
  margin-bottom: 8px;
}
.profile-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag {
  padding: 3px 10px;
  background: #1f2937;
  border-radius: 12px;
  font-size: 12px;
  color: #9ca3af;
}
.btn-chat {
  padding: 10px 20px;
  background: #3b82f6;
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
}
.btn-chat:hover {
  background: #2563eb;
}

/* Section */
.section {
  margin-bottom: 32px;
}
.section-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 16px;
}

/* Stances Table */
.stances-table {
  width: 100%;
  border-collapse: collapse;
}
.stances-table th {
  text-align: right;
  font-size: 12px;
  color: #6b7280;
  padding: 8px 12px;
  border-bottom: 1px solid #1f2937;
  font-weight: 500;
}
.stances-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #111318;
  font-size: 14px;
}
.stance-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.stance-badge.positive { background: #064e3b; color: #6ee7b7; }
.stance-badge.negative { background: #7f1d1d; color: #fca5a5; }
.stance-badge.neutral { background: #374151; color: #9ca3af; }
.strength-bar {
  height: 6px;
  background: #1f2937;
  border-radius: 3px;
  overflow: hidden;
  width: 100px;
}
.strength-fill {
  height: 100%;
  background: #60a5fa;
  border-radius: 3px;
}

/* Voting History */
.vote-history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vote-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: #1a1d27;
  border-radius: 6px;
  gap: 12px;
}
.vh-question {
  font-size: 13px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vh-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.vh-vote {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.vh-vote.for { background: #064e3b; color: #6ee7b7; }
.vh-vote.against { background: #7f1d1d; color: #fca5a5; }
.vh-vote.abstain { background: #374151; color: #9ca3af; }
.vh-date {
  font-size: 11px;
  color: #6b7280;
}

/* Memory Card */
.memory-card {
  padding: 16px 20px;
  background: #1a1d27;
  border: 1px solid #1f2937;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.7;
  color: #d1d5db;
}
.memory-card p { margin: 0; }

/* Chat Modal */
.chat-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.chat-modal {
  width: 480px;
  max-height: 70vh;
  background: #1a1d27;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #374151;
}
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid #1f2937;
}
.chat-header h3 {
  margin: 0;
  font-size: 15px;
}
.chat-close {
  background: none;
  border: none;
  color: #6b7280;
  font-size: 18px;
  cursor: pointer;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 200px;
}
.chat-msg {
  max-width: 80%;
}
.chat-msg.user {
  align-self: flex-start;
}
.chat-msg.mk {
  align-self: flex-end;
}
.msg-text {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
}
.chat-msg.user .msg-text {
  background: #3b82f6;
  color: white;
  border-bottom-right-radius: 4px;
}
.chat-msg.mk .msg-text {
  background: #374151;
  color: #e5e7eb;
  border-bottom-left-radius: 4px;
}
.typing {
  font-size: 20px;
  letter-spacing: 2px;
}
.chat-input-row {
  display: flex;
  border-top: 1px solid #1f2937;
}
.chat-input {
  flex: 1;
  padding: 12px 16px;
  background: transparent;
  border: none;
  color: #e5e7eb;
  font-size: 14px;
  outline: none;
  text-align: right;
}
.chat-send {
  padding: 12px 20px;
  background: #3b82f6;
  border: none;
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.chat-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
