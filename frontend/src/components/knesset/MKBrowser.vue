<template>
  <div class="mk-browser" dir="rtl">
    <!-- Toolbar -->
    <div class="browser-toolbar">
      <input
        v-model="searchQuery"
        type="text"
        placeholder='חיפוש ח"כ...'
        class="search-input"
      />
      <select v-model="filterFaction" class="faction-filter">
        <option value="all">כל הסיעות</option>
        <option v-for="f in uniqueFactions" :key="f" :value="f">{{ f }}</option>
      </select>
      <div class="side-filter">
        <button
          :class="{ active: filterSide === 'all' }"
          @click="filterSide = 'all'"
        >הכל</button>
        <button
          :class="{ active: filterSide === 'coalition' }"
          @click="filterSide = 'coalition'"
        >קואליציה</button>
        <button
          :class="{ active: filterSide === 'opposition' }"
          @click="filterSide = 'opposition'"
        >אופוזיציה</button>
      </div>
    </div>

    <!-- Count bar -->
    <div class="count-bar">
      מציג <strong>{{ filteredMKs.length }}</strong> מתוך <strong>{{ generatedMKs.length }}</strong> ח"כים
    </div>

    <!-- MK Grid -->
    <div v-if="filteredMKs.length === 0" class="empty-state">
      לא נמצאו ח"כים התואמים את החיפוש
    </div>
    <div v-else class="mk-grid">
      <div
        v-for="mk in filteredMKs"
        :key="mk.mk_id"
        class="mk-card"
        :style="{ '--faction-color': mk.faction_color || '#C9A84C' }"
        @click="emit('select-mk', mk)"
        role="button"
        tabindex="0"
        @keydown.enter="emit('select-mk', mk)"
        @keydown.space.prevent="emit('select-mk', mk)"
      >
        <!-- Avatar -->
        <div class="mk-avatar" :style="{ background: mk.faction_color || '#C9A84C' }">
          {{ avatarInitial(mk.name) }}
        </div>

        <!-- Name -->
        <div class="mk-name">{{ mk.name }}</div>

        <!-- Faction -->
        <div class="mk-faction">
          <div class="faction-pip" :style="{ background: mk.faction_color || '#C9A84C' }"></div>
          <span class="faction-label">{{ mk.faction }}</span>
        </div>

        <!-- Influence bar -->
        <div class="influence-row">
          <div class="influence-track">
            <div
              class="influence-fill"
              :style="{
                width: (mk.influence ?? 0) + '%',
                background: mk.faction_color || '#C9A84C',
              }"
            ></div>
          </div>
          <span class="influence-score">{{ mk.influence ?? 0 }}</span>
        </div>

        <!-- Side badge -->
        <div class="side-badge" :class="mk.side === 'coalition' ? 'badge-coalition' : 'badge-opposition'">
          {{ mk.side === 'coalition' ? 'קואליציה' : 'אופוזיציה' }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  mks: { type: Array, default: () => [] },
})

const emit = defineEmits(['select-mk'])

const searchQuery = ref('')
const filterFaction = ref('all')
const filterSide = ref('all') // 'all' | 'coalition' | 'opposition'

// Hardcoded Knesset 25 faction data (120 seats total)
const FACTIONS = [
  { name: 'ליכוד',            color: '#1e40af', seats: 32, side: 'coalition' },
  { name: 'יש עתיד',          color: '#06b6d4', seats: 24, side: 'opposition' },
  { name: 'הציונות הדתית',    color: '#ea580c', seats: 14, side: 'coalition' },
  { name: 'ש"ס',              color: '#0d9488', seats: 11, side: 'coalition' },
  { name: 'יהדות התורה',      color: '#374151', seats: 7,  side: 'coalition' },
  { name: 'העבודה',           color: '#dc2626', seats: 4,  side: 'opposition' },
  { name: 'מרצ',              color: '#16a34a', seats: 6,  side: 'opposition' },
  { name: 'חד"ש-רע"ם',        color: '#65a30d', seats: 10, side: 'opposition' },
  { name: 'ישראל ביתנו',      color: '#eab308', seats: 6,  side: 'opposition' },
  { name: 'המחנה הממלכתי',    color: '#3b82f6', seats: 6,  side: 'opposition' },
]

// Generate placeholder MKs from FACTIONS when no real data is provided
const generatedMKs = computed(() => {
  if (props.mks.length > 0) return props.mks
  const mks = []
  for (const f of FACTIONS) {
    for (let i = 0; i < f.seats; i++) {
      mks.push({
        mk_id: `${f.name}_${i}`,
        name: `ח"כ ${f.name} ${i + 1}`,
        faction: f.name,
        faction_color: f.color,
        side: f.side,
        influence: Math.round(30 + seededRandom(`${f.name}${i}`) * 70),
      })
    }
  }
  return mks
})

// Unique factions for the filter dropdown
const uniqueFactions = computed(() => {
  const set = new Set(generatedMKs.value.map(mk => mk.faction))
  return Array.from(set).sort()
})

// Filtered MKs based on search + filters
const filteredMKs = computed(() => {
  return generatedMKs.value.filter(mk => {
    if (searchQuery.value && !mk.name.includes(searchQuery.value)) return false
    if (filterFaction.value !== 'all' && mk.faction !== filterFaction.value) return false
    if (filterSide.value !== 'all' && mk.side !== filterSide.value) return false
    return true
  })
})

// Deterministic pseudo-random based on a seed string (avoids hydration mismatches)
function seededRandom(seed) {
  let hash = 0
  for (let i = 0; i < seed.length; i++) {
    hash = seed.charCodeAt(i) + ((hash << 5) - hash)
    hash |= 0
  }
  return (Math.abs(hash) % 1000) / 1000
}

function avatarInitial(name) {
  if (!name) return '?'
  // For Hebrew, get first non-space character; skip "ח"כ " prefix
  const cleaned = name.replace(/^ח"כ\s+/, '').trim()
  return cleaned.charAt(0) || '?'
}
</script>

<style scoped>
.mk-browser {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  color: var(--knesset-text, #E2E8F0);
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

/* ── Toolbar ── */
.browser-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-input {
  flex: 1;
  min-width: 120px;
  background: var(--knesset-surface, #1A2332);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 8px;
  color: var(--knesset-text, #E2E8F0);
  padding: 7px 12px;
  font-size: 0.82rem;
  outline: none;
  transition: border-color 0.2s;
  text-align: right;
}

.search-input::placeholder {
  color: #6B7280;
}

.search-input:focus {
  border-color: var(--knesset-gold, #C9A84C);
}

.faction-filter {
  background: var(--knesset-surface, #1A2332);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 8px;
  color: var(--knesset-text, #E2E8F0);
  padding: 7px 10px;
  font-size: 0.8rem;
  outline: none;
  cursor: pointer;
  text-align: right;
  transition: border-color 0.2s;
}

.faction-filter:focus {
  border-color: var(--knesset-gold, #C9A84C);
}

.side-filter {
  display: flex;
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-radius: 8px;
  overflow: hidden;
}

.side-filter button {
  background: transparent;
  border: none;
  border-right: 1px solid var(--knesset-border, #2A3A4A);
  color: #9CA3AF;
  padding: 7px 12px;
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  white-space: nowrap;
}

.side-filter button:first-child {
  border-right: none;
}

.side-filter button:last-child {
  border-right: none;
}

.side-filter button:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--knesset-text, #E2E8F0);
}

.side-filter button.active {
  background: rgba(201, 168, 76, 0.15);
  color: var(--knesset-gold, #C9A84C);
  font-weight: 600;
}

/* ── Count Bar ── */
.count-bar {
  font-size: 0.78rem;
  color: #6B7280;
  padding: 0 2px;
}

.count-bar strong {
  color: var(--knesset-text, #E2E8F0);
}

/* ── Empty State ── */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: #6B7280;
  font-size: 0.875rem;
  text-align: center;
}

/* ── MK Grid ── */
.mk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
  overflow-y: auto;
  padding: 2px 2px 8px;
}

/* ── MK Card ── */
.mk-card {
  background: var(--knesset-surface, #1A2332);
  border: 1px solid var(--knesset-border, #2A3A4A);
  border-right: 4px solid var(--faction-color, #C9A84C);
  border-radius: 10px;
  padding: 12px 10px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  text-align: center;
}

.mk-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
  border-top-color: color-mix(in srgb, var(--faction-color, #C9A84C) 40%, #2A3A4A);
}

.mk-card:focus-visible {
  outline: 2px solid var(--knesset-gold, #C9A84C);
  outline-offset: 2px;
}

/* Avatar */
.mk-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
}

/* Name */
.mk-name {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--knesset-text, #E2E8F0);
  line-height: 1.3;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  width: 100%;
}

/* Faction */
.mk-faction {
  display: flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
}

.faction-pip {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.faction-label {
  font-size: 0.7rem;
  color: #9CA3AF;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Influence bar */
.influence-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}

.influence-track {
  flex: 1;
  height: 5px;
  background: rgba(42, 58, 74, 0.8);
  border-radius: 3px;
  overflow: hidden;
}

.influence-fill {
  height: 100%;
  border-radius: 3px;
  opacity: 0.85;
  transition: width 0.3s ease;
}

.influence-score {
  font-size: 0.68rem;
  color: #9CA3AF;
  min-width: 20px;
  text-align: right;
}

/* Side badge */
.side-badge {
  font-size: 0.62rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 20px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.badge-coalition {
  background: rgba(34, 197, 94, 0.15);
  color: #86efac;
  border: 1px solid rgba(34, 197, 94, 0.25);
}

.badge-opposition {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.25);
}

/* Scrollbar */
.mk-grid::-webkit-scrollbar {
  width: 4px;
}

.mk-grid::-webkit-scrollbar-track {
  background: transparent;
}

.mk-grid::-webkit-scrollbar-thumb {
  background: #2A3A4A;
  border-radius: 2px;
}
</style>
