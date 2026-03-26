<template>
  <div class="vote-tally" dir="rtl">
    <div class="tally-header">
      <span class="tally-title">תוצאות הצבעה</span>
      <span class="tally-total">{{ animatedFor + animatedAgainst + animatedAbstain }} / {{ total }}</span>
    </div>

    <!-- Bar visualization -->
    <div class="tally-bar-container">
      <div class="tally-bar">
        <div
          class="bar-segment bar-for"
          :style="{ width: barForPct + '%' }"
        />
        <div
          class="bar-segment bar-against"
          :style="{ width: barAgainstPct + '%' }"
        />
        <div
          class="bar-segment bar-abstain"
          :style="{ width: barAbstainPct + '%' }"
        />
      </div>
      <!-- Majority threshold line -->
      <div class="majority-line" :style="{ right: majorityPct + '%' }">
        <span class="majority-label">61</span>
      </div>
    </div>

    <!-- Counts -->
    <div class="tally-counts">
      <div class="count-item count-for">
        <span class="count-dot" style="background: #22c55e"></span>
        <span class="count-label">בעד</span>
        <span class="count-value">{{ animatedFor }}</span>
      </div>
      <div class="count-item count-against">
        <span class="count-dot" style="background: #ef4444"></span>
        <span class="count-label">נגד</span>
        <span class="count-value">{{ animatedAgainst }}</span>
      </div>
      <div class="count-item count-abstain">
        <span class="count-dot" style="background: #eab308"></span>
        <span class="count-label">נמנע</span>
        <span class="count-value">{{ animatedAbstain }}</span>
      </div>
    </div>

    <!-- Result indicator -->
    <div v-if="votesFor + votesAgainst > 0" class="result-indicator" :class="resultClass">
      {{ resultText }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'

const props = defineProps({
  votesFor: { type: Number, default: 0 },
  votesAgainst: { type: Number, default: 0 },
  abstentions: { type: Number, default: 0 },
  total: { type: Number, default: 120 }
})

const animatedFor = ref(0)
const animatedAgainst = ref(0)
const animatedAbstain = ref(0)

function animateValue(targetRef, targetVal) {
  const duration = 600
  const start = targetRef.value
  const diff = targetVal - start
  if (diff === 0) return
  const startTime = performance.now()

  function step(now) {
    const elapsed = now - startTime
    const progress = Math.min(elapsed / duration, 1)
    const ease = 1 - Math.pow(1 - progress, 3)
    targetRef.value = Math.round(start + diff * ease)
    if (progress < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

watch(() => props.votesFor, (v) => animateValue(animatedFor, v), { immediate: true })
watch(() => props.votesAgainst, (v) => animateValue(animatedAgainst, v), { immediate: true })
watch(() => props.abstentions, (v) => animateValue(animatedAbstain, v), { immediate: true })

const barForPct = computed(() => (props.votesFor / props.total) * 100)
const barAgainstPct = computed(() => (props.votesAgainst / props.total) * 100)
const barAbstainPct = computed(() => (props.abstentions / props.total) * 100)
const majorityPct = computed(() => (61 / props.total) * 100)

const resultClass = computed(() => {
  if (props.votesFor >= 61) return 'result-passed'
  if (props.votesAgainst >= 61) return 'result-failed'
  return 'result-pending'
})

const resultText = computed(() => {
  if (props.votesFor >= 61) return 'אושר'
  if (props.votesAgainst >= 61) return 'נדחה'
  return 'ההצבעה נמשכת...'
})
</script>

<style scoped>
.vote-tally {
  background: #1f2937;
  border-radius: 8px;
  padding: 16px;
  color: #e5e7eb;
}
.tally-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.tally-title {
  font-size: 14px;
  font-weight: 600;
  color: #f3f4f6;
}
.tally-total {
  font-size: 12px;
  color: #9ca3af;
}
.tally-bar-container {
  position: relative;
  margin-bottom: 16px;
}
.tally-bar {
  display: flex;
  height: 28px;
  border-radius: 6px;
  overflow: hidden;
  background: #374151;
}
.bar-segment {
  transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  min-width: 0;
}
.bar-for { background: #22c55e; }
.bar-against { background: #ef4444; }
.bar-abstain { background: #eab308; }

.majority-line {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 2px;
  background: #f3f4f6;
  transform: translateX(50%);
}
.majority-label {
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  color: #9ca3af;
  white-space: nowrap;
}
.tally-counts {
  display: flex;
  gap: 20px;
  justify-content: center;
}
.count-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.count-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.count-label {
  color: #9ca3af;
  font-size: 12px;
}
.count-value {
  font-weight: 700;
  font-size: 18px;
  min-width: 28px;
  text-align: center;
}
.result-indicator {
  margin-top: 12px;
  text-align: center;
  font-weight: 700;
  font-size: 16px;
  padding: 6px 12px;
  border-radius: 6px;
}
.result-passed { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
.result-failed { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.result-pending { background: rgba(234, 179, 8, 0.1); color: #eab308; }
</style>
