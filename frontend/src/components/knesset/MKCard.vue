<template>
  <div
    class="mk-card"
    :style="{ borderRightColor: factionColor }"
    dir="rtl"
    @click="emit('select-mk', mk)"
  >
    <div class="mk-avatar" :style="{ background: factionColor }">
      {{ initials }}
    </div>

    <div class="mk-info">
      <div class="mk-name-row">
        <span class="mk-name">{{ mk.name_he }}</span>
        <span v-if="mk.is_current_mk" class="mk-active-badge">פעיל</span>
      </div>

      <span class="mk-faction-badge" :style="{ background: factionColor + '22', color: factionColor }">
        {{ mk.faction }}
      </span>

      <!-- Influence bar -->
      <div v-if="mk.influence_score != null" class="influence-row">
        <span class="influence-label">השפעה</span>
        <div class="influence-bar-bg">
          <div class="influence-bar-fill" :style="{ width: Math.min(mk.influence_score, 100) + '%', background: influenceGradient }" />
        </div>
        <span class="influence-value">{{ mk.influence_score }}</span>
      </div>

      <!-- Ideology tags -->
      <div v-if="mk.ideology_tags?.length" class="ideology-tags">
        <span v-for="tag in mk.ideology_tags" :key="tag" class="ideology-pill">{{ tag }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

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
  mk: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['select-mk'])

const factionColor = computed(() => FACTION_COLORS[props.mk.faction] ?? FACTION_COLORS['default'])

const initials = computed(() => {
  const parts = (props.mk.name_he || '').split(' ')
  if (parts.length >= 2) return parts[0][0] + parts[1][0]
  return (parts[0] || '?')[0]
})

const influenceGradient = computed(() => {
  const score = props.mk.influence_score ?? 0
  if (score >= 70) return '#22c55e'
  if (score >= 40) return '#eab308'
  return '#ef4444'
})
</script>

<style scoped>
.mk-card {
  display: flex;
  gap: 12px;
  background: #1f2937;
  border-radius: 8px;
  padding: 12px;
  border-right: 4px solid #6b7280;
  cursor: pointer;
  transition: background 0.15s;
  color: #e5e7eb;
}
.mk-card:hover {
  background: #374151;
}
.mk-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  color: #fff;
  flex-shrink: 0;
}
.mk-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mk-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.mk-name {
  font-weight: 600;
  font-size: 14px;
  color: #f3f4f6;
}
.mk-active-badge {
  font-size: 10px;
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
  padding: 1px 6px;
  border-radius: 10px;
}
.mk-faction-badge {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  width: fit-content;
}
.influence-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.influence-label {
  font-size: 10px;
  color: #9ca3af;
  flex-shrink: 0;
}
.influence-bar-bg {
  flex: 1;
  height: 6px;
  background: #374151;
  border-radius: 3px;
  overflow: hidden;
}
.influence-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.influence-value {
  font-size: 11px;
  font-weight: 600;
  color: #d1d5db;
  min-width: 22px;
  text-align: left;
}
.ideology-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}
.ideology-pill {
  font-size: 10px;
  background: #374151;
  color: #9ca3af;
  padding: 1px 6px;
  border-radius: 8px;
}
</style>
