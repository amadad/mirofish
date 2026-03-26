<template>
  <div class="brainstorm-view" dir="rtl">
    <!-- Phase banner -->
    <div :class="['phase-banner', phase === 'divergent' ? 'phase-divergent' : 'phase-convergent']">
      <span class="phase-label">
        {{ phase === 'divergent' ? 'שלב יצירתי' : 'שלב סינון' }}
      </span>
      <span class="round-indicator">סבב {{ roundNum }} / {{ maxRounds }}</span>
    </div>

    <!-- Idea cards grid -->
    <div class="ideas-grid">
      <div
        v-for="idea in sortedIdeas"
        :key="idea.idea_id"
        class="idea-card"
        :style="{ background: heatColor(idea.votes, maxVotes) }"
      >
        <div class="idea-header">
          <span class="idea-author">{{ idea.agent_name }}</span>
          <span class="vote-badge">👍 {{ idea.votes }}</span>
        </div>
        <p class="idea-content">{{ idea.content_he }}</p>
        <div class="idea-meta">סבב {{ idea.round_num }}</div>

        <!-- Build chain -->
        <div v-if="buildChains[idea.idea_id]?.length" class="build-chain">
          <details>
            <summary class="chain-toggle">
              🔗 בניות ({{ buildChains[idea.idea_id].length }})
            </summary>
            <div
              v-for="(addition, i) in buildChains[idea.idea_id]"
              :key="i"
              class="chain-entry"
            >
              <span class="chain-author">{{ addition.agent_name }}:</span>
              {{ addition.content }}
            </div>
          </details>
        </div>
      </div>
    </div>

    <!-- Critiques section -->
    <div v-if="critiques.length" class="critiques-section">
      <h4 class="section-title">ביקורות</h4>
      <div v-for="(critique, idx) in critiques" :key="idx" class="critique-entry">
        <span class="critique-agent">{{ critique.agent_name }}:</span>
        <span class="critique-text">{{ critique.content }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  ideas: { type: Array, default: () => [] },
  buildChains: { type: Object, default: () => ({}) },
  critiques: { type: Array, default: () => [] },
  phase: { type: String, default: 'divergent' },
  roundNum: { type: Number, default: 1 },
  maxRounds: { type: Number, default: 5 },
})

const maxVotes = computed(() => {
  if (!props.ideas.length) return 1
  return Math.max(...props.ideas.map(i => i.votes), 1)
})

const sortedIdeas = computed(() =>
  [...props.ideas].sort((a, b) => b.votes - a.votes)
)

function heatColor(votes, max) {
  const intensity = Math.round((votes / max) * 40) + 5
  return `hsl(140, 60%, ${95 - intensity}%)`
}
</script>

<style scoped>
.brainstorm-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
  font-family: 'Segoe UI', sans-serif;
}
.phase-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-radius: 8px;
  font-weight: 700;
}
.phase-divergent { background: #e3f2fd; color: #1565c0; }
.phase-convergent { background: #fce4ec; color: #c62828; }
.phase-label { font-size: 1.05rem; }
.round-indicator { font-size: 0.85rem; opacity: 0.8; }

.ideas-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.idea-card {
  border-radius: 10px;
  padding: 14px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  transition: transform 0.15s;
}
.idea-card:hover { transform: translateY(-2px); }
.idea-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.idea-author { font-weight: 600; font-size: 0.85rem; color: #333; }
.vote-badge {
  background: #fff;
  border: 1px solid #c8e6c9;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 700;
}
.idea-content { margin: 0; font-size: 0.9rem; line-height: 1.5; color: #222; }
.idea-meta { font-size: 0.75rem; color: #777; margin-top: 6px; }

.build-chain { margin-top: 8px; }
.chain-toggle {
  cursor: pointer;
  font-size: 0.8rem;
  color: #1565c0;
  font-weight: 600;
}
.chain-entry {
  font-size: 0.8rem;
  padding: 4px 8px;
  margin-top: 4px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 4px;
}
.chain-author { font-weight: 600; }

.critiques-section { background: #fff8e1; border-radius: 8px; padding: 12px; }
.section-title { margin: 0 0 8px; font-size: 0.95rem; color: #f57f17; }
.critique-entry {
  font-size: 0.85rem;
  padding: 4px 0;
  border-bottom: 1px solid #fff0c2;
}
.critique-agent { font-weight: 600; }
.critique-text { color: #555; }
</style>
