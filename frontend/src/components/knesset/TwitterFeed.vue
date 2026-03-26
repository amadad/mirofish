<template>
  <div class="twitter-feed" dir="rtl">
    <div class="feed-layout">
      <!-- Left: Tweet Feed (70%) -->
      <div class="tweet-column">
        <div v-if="tweets.length === 0" class="empty-state">
          <span class="empty-icon">🐦</span>
          <p>אין ציוצים עדיין — הסימולציה תייצר ציוצים לאחר כל סבב</p>
        </div>
        <div v-else class="tweet-list">
          <div
            v-for="(tweet, idx) in tweets"
            :key="idx"
            class="tweet-card"
          >
            <div class="tweet-header">
              <div
                class="avatar"
                :style="{ background: avatarColor(tweet.agent_id) }"
              >
                {{ avatarInitial(tweet.agent_name) }}
              </div>
              <div class="tweet-meta">
                <span class="agent-name">{{ tweet.agent_name }}</span>
                <span class="agent-handle">@{{ handleFrom(tweet) }}</span>
              </div>
              <span class="round-badge">סבב {{ tweet.round }}</span>
            </div>
            <p class="tweet-content">{{ tweet.content }}</p>
            <div class="tweet-engagement">
              <span class="eng-item">
                <span class="eng-icon">❤️</span>
                <span>{{ tweet.likes ?? 0 }}</span>
              </span>
              <span class="eng-item">
                <span class="eng-icon">🔄</span>
                <span>{{ tweet.rts ?? 0 }}</span>
              </span>
              <span class="eng-item">
                <span class="eng-icon">💬</span>
                <span>{{ tweet.replies ?? 0 }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Trending + Stats (30%) -->
      <div class="trending-sidebar">
        <h4 class="sidebar-title">טרנדינג</h4>
        <div v-if="trending.length === 0" class="trend-empty">
          אין נושאים עדיין
        </div>
        <div
          v-for="(topic, i) in trending"
          :key="i"
          class="trending-item"
        >
          <span class="trend-rank">#{{ i + 1 }}</span>
          <span class="trend-topic">{{ topic }}</span>
        </div>

        <h4 class="stats-title sidebar-title">מדדי מעורבות</h4>
        <div v-if="engagementStats.total_tweets" class="stat-row">
          <span class="stat-label">ציוצים סה"כ</span>
          <span class="stat-value">{{ engagementStats.total_tweets }}</span>
        </div>
        <div v-if="engagementStats.total_likes" class="stat-row">
          <span class="stat-label">❤️ לייקים</span>
          <span class="stat-value">{{ engagementStats.total_likes }}</span>
        </div>
        <div v-if="engagementStats.total_rts" class="stat-row">
          <span class="stat-label">🔄 ריטוויטים</span>
          <span class="stat-value">{{ engagementStats.total_rts }}</span>
        </div>
        <div v-if="engagementStats.total_replies" class="stat-row">
          <span class="stat-label">💬 תגובות</span>
          <span class="stat-value">{{ engagementStats.total_replies }}</span>
        </div>
        <div
          v-if="!engagementStats.total_tweets && !engagementStats.total_likes"
          class="stat-empty"
        >
          אין נתונים עדיין
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  tweets: { type: Array, default: () => [] },
  trending: { type: Array, default: () => [] },
  engagementStats: { type: Object, default: () => ({}) },
})

// Generate a consistent color from agent_id string
function avatarColor(agentId) {
  if (!agentId) return '#C9A84C'
  let hash = 0
  for (let i = 0; i < agentId.length; i++) {
    hash = agentId.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 55%, 38%)`
}

function avatarInitial(name) {
  if (!name) return '?'
  return name.trim().charAt(0).toUpperCase()
}

function handleFrom(tweet) {
  // Prefer agent_id as handle; fall back to transliterating first word of name
  if (tweet.agent_id) return tweet.agent_id.replace(/\s+/g, '_')
  if (tweet.agent_name) return tweet.agent_name.replace(/\s+/g, '_')
  return 'mk_agent'
}
</script>

<style scoped>
.twitter-feed {
  width: 100%;
  height: 100%;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  color: var(--knesset-text, #E2E8F0);
  background: var(--knesset-bg, #0C1222);
}

.feed-layout {
  display: flex;
  flex-direction: row;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

/* Tweet Column — 70% */
.tweet-column {
  flex: 0 0 70%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding-left: 4px;
}

.tweet-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
  color: #6B7280;
  text-align: center;
  flex: 1;
}

.empty-icon {
  font-size: 2.5rem;
  opacity: 0.5;
}

.empty-state p {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.6;
  max-width: 280px;
}

/* Tweet Card */
.tweet-card {
  background: var(--knesset-surface, #1A2332);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 12px;
  padding: 14px 16px;
  transition: border-color 0.2s ease;
}

.tweet-card:hover {
  border-color: #3D5068;
}

/* Tweet Header */
.tweet-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}

.tweet-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.agent-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--knesset-text, #E2E8F0);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-handle {
  font-size: 0.75rem;
  color: #6B7280;
  direction: ltr;
  text-align: right;
}

.round-badge {
  background: rgba(201, 168, 76, 0.15);
  color: var(--knesset-gold, #C9A84C);
  border: 1px solid rgba(201, 168, 76, 0.3);
  border-radius: 20px;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 8px;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Tweet Content */
.tweet-content {
  margin: 0 0 12px 0;
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--knesset-text, #E2E8F0);
  word-break: break-word;
}

/* Engagement Row */
.tweet-engagement {
  display: flex;
  gap: 20px;
  padding-top: 10px;
  border-top: 1px solid var(--knesset-border, #2A3A4A);
}

.eng-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.8rem;
  color: #9CA3AF;
}

.eng-icon {
  font-size: 0.9rem;
}

/* Trending Sidebar — 30% */
.trending-sidebar {
  flex: 0 0 30%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--knesset-surface, #1A2332);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 12px;
  padding: 14px 12px;
  overflow-y: auto;
  align-self: flex-start;
  min-height: 200px;
}

.sidebar-title {
  margin: 0 0 6px 0;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--knesset-gold, #C9A84C);
  border-bottom: 1px solid var(--knesset-border, #2A3A4A);
  padding-bottom: 6px;
}

.stats-title {
  margin-top: 14px;
}

.trending-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 4px;
  border-radius: 6px;
  transition: background 0.15s ease;
}

.trending-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.trend-rank {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--knesset-gold, #C9A84C);
  min-width: 20px;
  flex-shrink: 0;
}

.trend-topic {
  font-size: 0.8rem;
  color: var(--knesset-text, #E2E8F0);
  word-break: break-word;
}

.trend-empty {
  font-size: 0.78rem;
  color: #6B7280;
  padding: 4px 0;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 4px;
  border-bottom: 1px solid rgba(42, 58, 74, 0.5);
}

.stat-label {
  font-size: 0.78rem;
  color: #9CA3AF;
}

.stat-value {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--knesset-text, #E2E8F0);
}

.stat-empty {
  font-size: 0.78rem;
  color: #6B7280;
  text-align: center;
  padding: 8px 0;
}

/* Scrollbar styling */
.tweet-column::-webkit-scrollbar,
.trending-sidebar::-webkit-scrollbar {
  width: 4px;
}

.tweet-column::-webkit-scrollbar-track,
.trending-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.tweet-column::-webkit-scrollbar-thumb,
.trending-sidebar::-webkit-scrollbar-thumb {
  background: #2A3A4A;
  border-radius: 2px;
}
</style>
