<template>
  <div class="hemicycle-chart" dir="rtl">
    <svg :viewBox="`0 0 ${width} ${height}`" class="hemicycle-svg">
      <!-- Seat circles -->
      <g v-for="seat in computedSeats" :key="seat.mk_id ?? `empty-${seat._index}`">
        <circle
          :cx="seat.x"
          :cy="seat.y"
          :r="seatRadius"
          :fill="getSeatColor(seat)"
          :stroke="selectedMk === seat.mk_id ? '#C9A84C' : 'transparent'"
          :stroke-width="selectedMk === seat.mk_id ? 2.5 : 0"
          :class="['seat-circle', { speaking: seat.speaking }]"
          @mouseenter="hoveredSeat = seat"
          @mouseleave="hoveredSeat = null"
          @click="onSeatClick(seat)"
        />
        <!-- Speaking glow ring -->
        <circle
          v-if="seat.speaking"
          :cx="seat.x"
          :cy="seat.y"
          :r="seatRadius + 4"
          fill="none"
          stroke="#fbbf24"
          stroke-width="1.5"
          opacity="0.6"
          class="speaking-ring"
        />
      </g>

      <!-- Speaker podium -->
      <rect :x="cx - 36" :y="height - 52" width="72" height="28" rx="6" fill="#1A2332" stroke="#2A3A4A" stroke-width="1" />
      <text :x="cx" :y="height - 35" text-anchor="middle" fill="#9ca3af" font-size="11" font-family="sans-serif">יו&quot;ר</text>

      <!-- Vote progress bar below podium -->
      <g v-if="totalVotes > 0" :transform="`translate(${cx - voteBarWidth / 2}, ${height - 18})`">
        <rect width="voteBarWidth" height="8" rx="4" fill="#1f2937" />
        <rect
          :width="(voteTallyLocal.for / totalVotes) * voteBarWidth"
          height="8" rx="4" fill="#16a34a"
        />
        <rect
          :x="(voteTallyLocal.for / totalVotes) * voteBarWidth"
          :width="(voteTallyLocal.against / totalVotes) * voteBarWidth"
          height="8" fill="#dc2626"
        />
        <rect
          :x="((voteTallyLocal.for + voteTallyLocal.against) / totalVotes) * voteBarWidth"
          :width="(voteTallyLocal.abstain / totalVotes) * voteBarWidth"
          height="8" fill="#f59e0b"
        />
        <text x="0" y="20" fill="#6b7280" font-size="9" font-family="sans-serif">
          בעד {{ voteTallyLocal.for }} | נגד {{ voteTallyLocal.against }} | נמנע {{ voteTallyLocal.abstain }}
        </text>
      </g>

      <!-- Current bill label -->
      <text
        v-if="currentBill"
        :x="cx"
        y="18"
        text-anchor="middle"
        fill="#C9A84C"
        font-size="11"
        font-family="sans-serif"
      >{{ currentBill }}</text>

      <!-- Tooltip -->
      <g v-if="hoveredSeat && hoveredSeat.name" :transform="`translate(${tooltipPos.x}, ${tooltipPos.y})`">
        <rect x="-68" y="-36" width="136" height="32" rx="5" fill="#1A2332" stroke="#2A3A4A" stroke-width="1" />
        <text x="0" y="-20" text-anchor="middle" fill="#E2E8F0" font-size="11" font-family="sans-serif">
          {{ hoveredSeat.name }}
        </text>
        <text x="0" y="-8" text-anchor="middle" fill="#9ca3af" font-size="10" font-family="sans-serif">
          {{ hoveredSeat.faction }}
        </text>
      </g>
    </svg>

    <!-- Faction legend -->
    <div class="faction-legend">
      <span v-for="(color, name) in mergedColors" :key="name" class="legend-item" v-show="name !== 'default'">
        <span class="legend-dot" :style="{ background: color }"></span>
        {{ name }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  seats: {
    type: Array,
    default: () => []
  },
  factionColors: {
    type: Object,
    default: () => ({})
  },
  voteTally: {
    type: Object,
    default: () => null
  },
  currentBill: {
    type: String,
    default: ''
  },
})

const emit = defineEmits(['select-mk'])

const FACTION_COLORS = {
  'ליכוד': '#1e40af',
  'הציונות הדתית': '#ea580c',
  'ש"ס': '#0d9488',
  'יהדות התורה': '#374151',
  'עוצמה יהודית': '#7c3aed',
  'נועם': '#4b5563',
  'יש עתיד': '#06b6d4',
  'המחנה הממלכתי': '#3b82f6',
  'ישראל ביתנו': '#eab308',
  'העבודה': '#dc2626',
  'מרצ': '#16a34a',
  'חד"ש-תע"ל': '#65a30d',
  'חד"ש-רע"ם': '#65a30d',
  'רע"ם': '#059669',
  'בל"ד': '#84cc16',
  'default': '#6b7280'
}

const width = 500
const height = 320
const cx = width / 2
const cy = height - 60
const seatRadius = 7
const voteBarWidth = 160
const seatsPerRow = [24, 22, 20, 18, 14, 12, 10]

const hoveredSeat = ref(null)
const selectedMk = ref(null)

const mergedColors = computed(() => ({ ...FACTION_COLORS, ...props.factionColors }))

const voteTallyLocal = computed(() => {
  if (props.voteTally) return props.voteTally
  // count from seats
  const tally = { for: 0, against: 0, abstain: 0 }
  for (const seat of props.seats) {
    if (seat.vote_status === 'בעד') tally.for++
    else if (seat.vote_status === 'נגד') tally.against++
    else if (seat.vote_status === 'נמנע') tally.abstain++
  }
  return tally
})

const totalVotes = computed(() =>
  voteTallyLocal.value.for + voteTallyLocal.value.against + voteTallyLocal.value.abstain
)

const tooltipPos = computed(() => {
  if (!hoveredSeat.value) return { x: 0, y: 0 }
  // Clamp tooltip to stay within SVG bounds
  const tx = Math.max(70, Math.min(width - 70, hoveredSeat.value.x))
  const ty = Math.max(40, hoveredSeat.value.y - 10)
  return { x: tx, y: ty }
})

const computedSeats = computed(() => {
  const result = []
  let seatIdx = 0

  for (let row = 0; row < seatsPerRow.length; row++) {
    const radius = 220 - row * 28
    const count = seatsPerRow[row]
    const padding = 0.08

    for (let i = 0; i < count; i++) {
      const angle = padding + (Math.PI - 2 * padding) * (i / (count - 1))
      const x = cx + radius * Math.cos(Math.PI - angle)
      const y = cy - radius * Math.sin(angle)

      const seatData = props.seats[seatIdx] ?? {}
      result.push({
        ...seatData,
        _index: seatIdx,
        x,
        y,
        row,
        col: i
      })
      seatIdx++
    }
  }
  return result
})

function getSeatColor(seat) {
  if (seat.vote_status === 'בעד') return '#16a34a'
  if (seat.vote_status === 'נגד') return '#dc2626'
  if (seat.vote_status === 'נמנע') return '#f59e0b'
  const faction = seat.faction
  if (!faction) return mergedColors.value['default']
  return mergedColors.value[faction] ?? mergedColors.value['default']
}

function onSeatClick(seat) {
  if (!seat.mk_id) return
  selectedMk.value = seat.mk_id
  emit('select-mk', seat)
}
</script>

<style scoped>
.hemicycle-chart {
  width: 100%;
  height: 100%;
  background: #0C1222;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.hemicycle-svg {
  flex: 1;
  width: 100%;
  height: auto;
  min-height: 0;
}
.seat-circle {
  cursor: pointer;
  transition: opacity 0.15s, filter 0.15s;
}
.seat-circle:hover {
  filter: brightness(1.4);
}
.seat-circle.speaking {
  filter: brightness(1.6);
}
.speaking-ring {
  animation: pulse-ring 1.2s ease-in-out infinite;
}
@keyframes pulse-ring {
  0%, 100% { opacity: 0.6; r: 11; }
  50% { opacity: 0.2; r: 14; }
}

/* Faction legend */
.faction-legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px 12px;
  padding: 8px 12px;
  border-top: 1px solid #2A3A4A;
  flex-shrink: 0;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #6b7280;
  font-family: -apple-system, sans-serif;
}
.legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
</style>
