<template>
  <div class="decision-view" dir="rtl">
    <!-- Phase banner with step indicator -->
    <div class="phase-steps">
      <div
        v-for="(step, idx) in phaseSteps"
        :key="step.id"
        :class="['step', { 'step-active': phase === step.id, 'step-done': stepIndex > idx }]"
      >
        <span class="step-num">{{ idx + 1 }}</span>
        <span class="step-label">{{ step.label }}</span>
      </div>
    </div>

    <!-- Options grid with analysis -->
    <div class="options-grid" :style="{ gridTemplateColumns: `repeat(${options.length || 1}, 1fr)` }">
      <div
        v-for="option in options"
        :key="option.option_id"
        :class="['option-column', { 'option-winner': decision === option.option_id }]"
      >
        <div class="option-header">
          <span class="option-text">{{ option.text_he }}</span>
          <span v-if="decision === option.option_id" class="winner-badge">🏆 נבחר</span>
        </div>

        <!-- Analysis entries for this option -->
        <div class="analysis-stack">
          <div
            v-for="(entry, idx) in optionAnalysis(option.option_id)"
            :key="idx"
            :class="['analysis-card', stanceBorder(entry.stance)]"
          >
            <div class="analysis-header">
              <span class="analysis-agent">
                {{ isDevil(entry.agent_id) ? '😈 ' : '' }}{{ entry.agent_name }}
              </span>
              <span :class="['stance-tag', 'stance-' + entry.stance]">
                {{ stanceLabel(entry.stance) }}
              </span>
            </div>
            <p class="analysis-text">{{ entry.content }}</p>
          </div>
        </div>

        <!-- Vote bar for this option -->
        <div v-if="phase === 'vote' || decision" class="vote-bar-container">
          <div class="vote-bar">
            <div
              class="vote-bar-fill"
              :style="{ width: votePercent(option.option_id) + '%' }"
            />
          </div>
          <span class="vote-count">{{ voteTally[option.option_id] || 0 }} קולות</span>
        </div>
      </div>
    </div>

    <!-- Decision result -->
    <div v-if="decision" class="decision-result">
      <span class="decision-label">החלטה:</span>
      <span class="decision-text">
        {{ options.find(o => o.option_id === decision)?.text_he || decision }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  options: { type: Array, default: () => [] },
  analysisLog: { type: Array, default: () => [] },
  votes: { type: Object, default: () => ({}) },
  phase: { type: String, default: 'analysis' },
  decision: { type: [String, null], default: null },
  devilAdvocates: { type: Object, default: () => ({}) },
})

const phaseSteps = [
  { id: 'analysis', label: 'ניתוח' },
  { id: 'debate', label: 'דיון' },
  { id: 'vote', label: 'הצבעה' },
]

const stepIndex = computed(() => phaseSteps.findIndex(s => s.id === props.phase))

const voteTally = computed(() => {
  const tally = {}
  for (const round of Object.values(props.votes)) {
    for (const optionId of Object.values(round)) {
      tally[optionId] = (tally[optionId] || 0) + 1
    }
  }
  return tally
})

const totalVotes = computed(() =>
  Object.values(voteTally.value).reduce((s, v) => s + v, 0) || 1
)

function optionAnalysis(optionId) {
  return props.analysisLog.filter(e => e.option_id === optionId)
}

function isDevil(agentId) {
  return Object.values(props.devilAdvocates).includes(agentId)
}

function stanceBorder(stance) {
  const map = { pro: 'border-green', con: 'border-red', neutral: 'border-gray' }
  return map[stance] || 'border-gray'
}

function stanceLabel(stance) {
  const map = { pro: 'בעד', con: 'נגד', neutral: 'ניטרלי' }
  return map[stance] || stance
}

function votePercent(optionId) {
  return Math.round(((voteTally.value[optionId] || 0) / totalVotes.value) * 100)
}
</script>

<style scoped>
.decision-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-family: 'Segoe UI', sans-serif;
}

.phase-steps {
  display: flex;
  gap: 4px;
  background: #f5f5f5;
  border-radius: 8px;
  padding: 6px;
}
.step {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px;
  border-radius: 6px;
  font-size: 0.85rem;
  color: #999;
  transition: all 0.2s;
}
.step-active { background: #1565c0; color: #fff; font-weight: 700; }
.step-done { color: #2e7d32; }
.step-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  border: 2px solid currentColor;
}
.step-active .step-num { background: #fff; color: #1565c0; border-color: #fff; }

.options-grid { display: grid; gap: 12px; }
.option-column {
  background: #fafafa;
  border-radius: 10px;
  padding: 14px;
  border: 2px solid transparent;
  transition: border-color 0.3s;
}
.option-winner {
  border-color: #ffd700;
  background: linear-gradient(135deg, #fffde7 0%, #fff8e1 100%);
  box-shadow: 0 0 16px rgba(255, 215, 0, 0.25);
}
.option-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.option-text { font-weight: 700; font-size: 1rem; color: #1a1a2e; }
.winner-badge {
  font-size: 0.8rem;
  background: #ffd700;
  padding: 2px 10px;
  border-radius: 12px;
  font-weight: 700;
}

.analysis-stack { display: flex; flex-direction: column; gap: 8px; }
.analysis-card {
  padding: 10px 12px;
  border-radius: 6px;
  background: #fff;
  border-right: 4px solid;
}
.border-green { border-right-color: #4caf50; }
.border-red { border-right-color: #ef5350; }
.border-gray { border-right-color: #bdbdbd; }
.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.analysis-agent { font-weight: 600; font-size: 0.8rem; }
.stance-tag {
  font-size: 0.7rem;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.stance-pro { background: #e8f5e9; color: #2e7d32; }
.stance-con { background: #ffebee; color: #c62828; }
.stance-neutral { background: #f5f5f5; color: #616161; }
.analysis-text { margin: 0; font-size: 0.85rem; color: #444; line-height: 1.5; }

.vote-bar-container { margin-top: 12px; }
.vote-bar {
  height: 10px;
  background: #e0e0e0;
  border-radius: 5px;
  overflow: hidden;
}
.vote-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #42a5f5, #1565c0);
  border-radius: 5px;
  transition: width 0.4s ease;
}
.vote-count { font-size: 0.75rem; color: #666; margin-top: 2px; display: block; }

.decision-result {
  background: linear-gradient(135deg, #e8f5e9, #c8e6c9);
  padding: 14px 20px;
  border-radius: 10px;
  text-align: center;
}
.decision-label { font-weight: 700; font-size: 1.1rem; color: #2e7d32; }
.decision-text { font-size: 1.05rem; color: #1b5e20; margin-right: 8px; }
</style>
