<template>
  <div class="faction-bar" dir="rtl">
    <div class="faction-bar-header">
      <div class="side-label coalition-label">
        <span class="side-name">קואליציה</span>
        <span class="side-seats">{{ coalitionTotal }}</span>
      </div>
      <div class="side-label opposition-label">
        <span class="side-seats">{{ oppositionTotal }}</span>
        <span class="side-name">אופוזיציה</span>
      </div>
    </div>

    <div class="bar-container">
      <!-- Coalition segments -->
      <div
        v-for="f in coalitionFactions"
        :key="f.name_he"
        class="bar-segment"
        :style="{ width: segmentPct(f.seats) + '%', background: getFactionColor(f.name_he) }"
        :title="f.name_he + ' (' + f.seats + ')'"
      >
        <span v-if="f.seats >= 5" class="segment-label">{{ f.seats }}</span>
      </div>

      <!-- Divider -->
      <div class="bar-divider" />

      <!-- Opposition segments -->
      <div
        v-for="f in oppositionFactions"
        :key="f.name_he"
        class="bar-segment"
        :style="{ width: segmentPct(f.seats) + '%', background: getFactionColor(f.name_he) }"
        :title="f.name_he + ' (' + f.seats + ')'"
      >
        <span v-if="f.seats >= 5" class="segment-label">{{ f.seats }}</span>
      </div>
    </div>

    <!-- Majority line -->
    <div class="majority-marker" :style="{ right: majorityPct + '%' }">
      <div class="majority-tick" />
      <span class="majority-text">61</span>
    </div>

    <!-- Legend -->
    <div class="faction-legend">
      <div
        v-for="f in allSorted"
        :key="f.name_he"
        class="legend-item"
        :class="{ 'legend-coalition': f.coalition, 'legend-opposition': !f.coalition }"
      >
        <span class="legend-dot" :style="{ background: getFactionColor(f.name_he) }" />
        <span class="legend-name">{{ f.name_he }}</span>
        <span class="legend-seats">{{ f.seats }}</span>
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
  factions: {
    type: Array,
    default: () => []
  }
})

function getFactionColor(name) {
  return FACTION_COLORS[name] ?? FACTION_COLORS['default']
}

const coalitionFactions = computed(() =>
  props.factions.filter(f => f.coalition).sort((a, b) => b.seats - a.seats)
)

const oppositionFactions = computed(() =>
  props.factions.filter(f => !f.coalition).sort((a, b) => b.seats - a.seats)
)

const allSorted = computed(() =>
  [...coalitionFactions.value, ...oppositionFactions.value]
)

const coalitionTotal = computed(() =>
  coalitionFactions.value.reduce((s, f) => s + f.seats, 0)
)

const oppositionTotal = computed(() =>
  oppositionFactions.value.reduce((s, f) => s + f.seats, 0)
)

const totalSeats = computed(() => coalitionTotal.value + oppositionTotal.value || 120)

function segmentPct(seats) {
  return (seats / totalSeats.value) * 100
}

const majorityPct = computed(() => (61 / totalSeats.value) * 100)
</script>

<style scoped>
.faction-bar {
  background: #1f2937;
  border-radius: 8px;
  padding: 14px;
  color: #e5e7eb;
  position: relative;
}
.faction-bar-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}
.side-label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.side-name {
  font-size: 12px;
  color: #9ca3af;
}
.side-seats {
  font-size: 16px;
  font-weight: 700;
  color: #f3f4f6;
}
.bar-container {
  display: flex;
  height: 32px;
  border-radius: 6px;
  overflow: hidden;
  background: #374151;
  position: relative;
}
.bar-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 2px;
  transition: width 0.4s ease;
  position: relative;
}
.segment-label {
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}
.bar-divider {
  width: 3px;
  background: #111827;
  flex-shrink: 0;
}
.majority-marker {
  position: absolute;
  top: 36px;
  transform: translateX(50%);
}
.majority-tick {
  width: 2px;
  height: 40px;
  background: #f3f4f6;
  margin: 0 auto;
}
.majority-text {
  display: block;
  text-align: center;
  font-size: 10px;
  color: #9ca3af;
  margin-top: 2px;
}
.faction-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 50px;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-name {
  color: #d1d5db;
}
.legend-seats {
  color: #6b7280;
  font-weight: 600;
}
</style>
