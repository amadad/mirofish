<template>
  <div class="knesset-home" dir="rtl">

    <!-- Header -->
    <header class="knesset-header">
      <div class="brand" @click="$router.push('/')">MIROFISH</div>
      <nav class="nav-links">
        <router-link to="/knesset">ראשי</router-link>
        <router-link to="/knesset/history">הצעות חוק</router-link>
      </nav>
    </header>

    <!-- Hero -->
    <section class="hero">
      <div class="hero-icon">🏛️</div>
      <h1 class="hero-title">הכנסת הווירטואלית</h1>
      <p class="hero-subtitle">סימולטור חקיקה מבוסס בינה מלאכותית — 120 ח"כים, דיונים אמיתיים, הצבעות חיות</p>
    </section>

    <!-- 3 Input Channels -->
    <section class="input-section">
      <div class="input-tabs">
        <button
          v-for="tab in inputTabs"
          :key="tab.id"
          class="input-tab"
          :class="{ active: inputMode === tab.id }"
          @click="inputMode = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Text Mode -->
      <div v-if="inputMode === 'text'" class="input-panel">
        <textarea
          v-model="question"
          class="question-textarea"
          placeholder="מה תרצה לבדוק?"
          rows="3"
          @keydown.ctrl.enter="startSimulation"
        ></textarea>
      </div>

      <!-- Upload Mode -->
      <div v-else-if="inputMode === 'upload'" class="input-panel">
        <div
          class="upload-zone"
          :class="{ 'drag-over': isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDrop"
          @click="triggerFileInput"
        >
          <span class="upload-icon">📄</span>
          <span class="upload-label">גרור קובץ לכאן או לחץ לבחירה</span>
          <span class="upload-filename" v-if="uploadedFile">{{ uploadedFile.name }}</span>
          <input ref="fileInputRef" type="file" class="hidden-file-input" @change="onFileChange" />
        </div>
        <div class="upload-type-select">
          <button
            v-for="t in uploadTypes"
            :key="t.id"
            class="upload-type-btn"
            :class="{ active: uploadType === t.id }"
            @click="uploadType = t.id"
          >
            {{ t.label }}
          </button>
        </div>
      </div>

      <!-- Scenarios Mode -->
      <div v-else-if="inputMode === 'scenarios'" class="input-panel">
        <div class="scenarios-grid">
          <button
            v-for="sc in SCENARIOS"
            :key="sc.id"
            class="scenario-card"
            @click="selectScenario(sc)"
          >
            <span class="sc-icon">{{ sc.icon }}</span>
            <span class="sc-label">{{ sc.label }}</span>
            <span class="sc-question">{{ sc.question }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- Config Panel -->
    <section class="config-section">
      <div class="config-card">

        <!-- Platform -->
        <div class="config-row">
          <label class="config-label">פלטפורמה</label>
          <div class="platform-select">
            <select v-model="platform" class="config-select">
              <option v-for="p in PLATFORMS" :key="p.id" :value="p.id">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <!-- Rounds -->
        <div class="config-row">
          <label class="config-label">סבבים: <strong class="config-value-display">{{ rounds }}</strong></label>
          <div class="slider-wrapper">
            <input
              type="range"
              min="1"
              max="50"
              v-model.number="rounds"
              class="rounds-slider"
            />
            <div class="slider-range-labels">
              <span>1</span>
              <span>50</span>
            </div>
          </div>
        </div>

        <!-- Social Layer -->
        <div class="config-row config-row-inline">
          <label class="config-label">שכבה חברתית</label>
          <button
            class="toggle-switch"
            :class="{ on: socialLayer }"
            @click="socialLayer = !socialLayer"
            :aria-pressed="socialLayer"
            role="switch"
          >
            <span class="toggle-knob"></span>
          </button>
        </div>

        <!-- Quality Tier -->
        <div class="config-row">
          <label class="config-label">רמת איכות</label>
          <div class="quality-tiers">
            <button
              v-for="tier in QUALITY_TIERS"
              :key="tier.id"
              class="tier-btn"
              :class="{ active: qualityTier === tier.id }"
              @click="qualityTier = tier.id"
            >
              <span class="tier-label">{{ tier.label }}</span>
              <span class="tier-desc">{{ tier.desc }}</span>
            </button>
          </div>
        </div>

        <!-- Modifiers -->
        <div class="config-row">
          <label class="config-label">תוספות</label>
          <div class="modifiers-list">
            <label
              v-for="mod in MODIFIER_OPTIONS"
              :key="mod.id"
              class="modifier-item"
            >
              <input
                type="checkbox"
                :value="mod.id"
                v-model="modifiers"
                class="modifier-checkbox"
              />
              <span>{{ mod.label }}</span>
            </label>
          </div>
        </div>
      </div>
    </section>

    <!-- Launch Button -->
    <section class="launch-section">
      <button
        class="launch-btn"
        @click="startSimulation"
        :disabled="!canLaunch || loading"
      >
        <span v-if="loading" class="spinner"></span>
        <span v-else>🚀 הפעל סימולציה</span>
      </button>
    </section>

    <!-- Stats Row -->
    <section class="stats-row">
      <div class="stat-card" v-for="stat in stats" :key="stat.label">
        <span class="stat-value">{{ stat.value }}</span>
        <span class="stat-label">{{ stat.label }}</span>
      </div>
    </section>

    <!-- Recent Simulations -->
    <section class="recent-section" v-if="recentSimulations.length">
      <h2 class="section-title">הדמיות אחרונות</h2>
      <div class="recent-grid">
        <div
          v-for="sim in recentSimulations"
          :key="sim.id"
          class="recent-card"
          @click="$router.push(`/knesset/simulate/${sim.id}`)"
        >
          <div class="recent-question">{{ sim.question_he }}</div>
          <div class="recent-meta">
            <span class="recent-status" :class="sim.status">{{ statusLabel(sim.status) }}</span>
            <span class="recent-date">{{ formatDate(sim.created_at) }}</span>
          </div>
          <div class="recent-result" v-if="sim.result">
            {{ sim.result.passed ? 'אושרה' : 'נדחתה' }} — {{ sim.result.for }}/{{ sim.result.against }}
          </div>
        </div>
      </div>
    </section>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { runSimulation as apiRunSim, getStats } from '../../api/knesset'

const router = useRouter()

// ── Input ──────────────────────────────────────────────
const inputMode = ref('text')
const question = ref('')
const isDragging = ref(false)
const uploadedFile = ref(null)
const uploadType = ref('bill')
const fileInputRef = ref(null)

const inputTabs = [
  { id: 'text',      label: 'טקסט חופשי' },
  { id: 'upload',    label: 'העלאת קובץ' },
  { id: 'scenarios', label: 'תרחישים' },
]

const uploadTypes = [
  { id: 'bill',     label: 'הצעת חוק' },
  { id: 'protocol', label: 'פרוטוקול' },
  { id: 'data',     label: 'נתונים' },
  { id: 'article',  label: 'כתבה' },
]

const SCENARIOS = [
  { id: 'cannabis',  label: 'לגליזציה',        question: 'חוק לגליזציה של קנאביס לשימוש פרטי',           icon: '🌿' },
  { id: 'transport', label: 'תחבורה בשבת',     question: 'חוק תחבורה ציבורית בשבת ובחגים',               icon: '🚌' },
  { id: 'housing',   label: 'דיור בר-השגה',    question: 'חוק הגבלת מחירי שכירות',                       icon: '🏠' },
  { id: 'draft',     label: 'גיוס שוויוני',    question: 'חוק גיוס שוויוני לכלל האוכלוסייה',             icon: '🎖️' },
  { id: 'budget',    label: 'תקציב המדינה',    question: 'דיון בתקציב המדינה לשנת 2025',                 icon: '💰' },
  { id: 'security',  label: 'משבר ביטחוני',    question: 'ישיבת חירום בנושא אירוע ביטחוני',              icon: '🛡️' },
]

function selectScenario(sc) {
  question.value = sc.question
  inputMode.value = 'text'
}

function onDrop(e) {
  isDragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) uploadedFile.value = file
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

function onFileChange(e) {
  const file = e.target.files[0]
  if (file) uploadedFile.value = file
}

// ── Config ─────────────────────────────────────────────
const platform    = ref('plenum')
const rounds      = ref(5)
const socialLayer = ref(true)
const qualityTier = ref('standard')
const modifiers   = ref([])

const PLATFORMS = [
  { id: 'plenum',          label: 'מליאה - דיון כללי' },
  { id: 'committee',       label: 'ועדה - דיון מצומצם' },
  { id: 'negotiation',     label: 'מו"מ קואליציוני' },
  { id: 'brainstorm',      label: 'סיעור מוחות' },
  { id: 'decision',        label: 'קבלת החלטות' },
  { id: 'press_conference',label: 'מסיבת עיתונאים' },
  { id: 'twitter',         label: 'עצרת טוויטר' },
  { id: 'custom',          label: 'מותאם אישית' },
]

const QUALITY_TIERS = [
  { id: 'economy',  label: 'חסכוני',   desc: 'מהיר וזול' },
  { id: 'standard', label: 'סטנדרטי',  desc: 'מאוזן' },
  { id: 'premium',  label: 'פרמיום',   desc: 'איכות מרבית' },
]

const MODIFIER_OPTIONS = [
  { id: 'security_crisis', label: 'משבר ביטחוני' },
  { id: 'mk_leaving',      label: 'ח"כ עוזב סיעה' },
  { id: 'elections',       label: 'ערב בחירות' },
]

// ── Launch ─────────────────────────────────────────────
const loading = ref(false)
const canLaunch = computed(() => question.value.trim().length > 0)

async function startSimulation() {
  if (!canLaunch.value || loading.value) return
  loading.value = true
  try {
    const res = await apiRunSim(question.value.trim(), rounds.value, null)
    if (res?.data?.simulation_id) {
      router.push({
        name: 'KnessetSimulate',
        query: {
          q:       question.value.trim(),
          simId:   res.data.simulation_id,
          platform: platform.value,
          rounds:  rounds.value,
        },
      })
    }
  } catch (e) {
    console.error('Failed to start simulation:', e)
    alert('שגיאה בהפעלת ההדמיה')
  } finally {
    loading.value = false
  }
}

// ── Stats + Recent ─────────────────────────────────────
const stats = ref([
  { label: 'חברי כנסת',  value: '120' },
  { label: 'סיעות',       value: '—' },
  { label: 'הצעות חוק',  value: '—' },
  { label: 'הדמיות',      value: '—' },
])

const recentSimulations = ref([])

onMounted(async () => {
  try {
    const res = await getStats()
    if (res?.data) {
      stats.value = [
        { label: 'חברי כנסת',  value: String(res.data.mks_count         || 120) },
        { label: 'סיעות',       value: String(res.data.factions_count    || '—') },
        { label: 'הצעות חוק',  value: String(res.data.bills_count       || '—') },
        { label: 'הדמיות',      value: String(res.data.simulations_count || '—') },
      ]
      if (res.data.recent_simulations) {
        recentSimulations.value = res.data.recent_simulations
      }
    }
  } catch (e) {
    console.warn('Stats unavailable:', e.message)
  }
})

function statusLabel(status) {
  const map = { running: 'פעיל', completed: 'הושלם', failed: 'נכשל', pending: 'ממתין' }
  return map[status] || status
}

function formatDate(d) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('he-IL')
}
</script>

<style scoped>
/* ── CSS Variables ─────────────────────────────────── */
:root {
  --knesset-bg:      #0C1222;
  --knesset-surface: #1A2332;
  --knesset-border:  #2A3A4A;
  --knesset-text:    #E2E8F0;
  --knesset-gold:    #C9A84C;
}

/* ── Base ──────────────────────────────────────────── */
.knesset-home {
  min-height: 100vh;
  background: #0C1222;
  color: #E2E8F0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

/* ── Header ────────────────────────────────────────── */
.knesset-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 32px;
  border-bottom: 1px solid #2A3A4A;
  background: #0C1222;
  position: sticky;
  top: 0;
  z-index: 10;
}

.brand {
  font-size: 18px;
  font-weight: 700;
  color: #C9A84C;
  cursor: pointer;
  letter-spacing: 2px;
}

.nav-links {
  display: flex;
  gap: 24px;
}

.nav-links a {
  color: #94a3b8;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}

.nav-links a:hover,
.nav-links a.router-link-active {
  color: #E2E8F0;
}

/* ── Hero ──────────────────────────────────────────── */
.hero {
  text-align: center;
  padding: 64px 24px 40px;
}

.hero-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.hero-title {
  font-size: 44px;
  font-weight: 800;
  background: linear-gradient(135deg, #C9A84C, #e8c97a);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0 0 14px;
}

.hero-subtitle {
  font-size: 17px;
  color: #94a3b8;
  margin: 0 auto;
  max-width: 580px;
  line-height: 1.6;
}

/* ── Input Section ─────────────────────────────────── */
.input-section {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 24px 8px;
}

.input-tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid #2A3A4A;
  margin-bottom: 20px;
}

.input-tab {
  padding: 10px 20px;
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  position: relative;
  transition: color 0.2s;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
}

.input-tab:hover {
  color: #E2E8F0;
}

.input-tab.active {
  color: #C9A84C;
  border-bottom-color: #C9A84C;
}

.input-panel {
  min-height: 160px;
}

/* Text Mode */
.question-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 18px;
  background: #1A2332;
  border: 1px solid #2A3A4A;
  border-radius: 10px;
  color: #E2E8F0;
  font-size: 16px;
  font-family: inherit;
  resize: vertical;
  text-align: right;
  direction: rtl;
  outline: none;
  transition: border-color 0.2s;
  line-height: 1.6;
}

.question-textarea::placeholder {
  color: #475569;
}

.question-textarea:focus {
  border-color: #C9A84C;
}

/* Upload Mode */
.upload-zone {
  border: 2px dashed #2A3A4A;
  border-radius: 10px;
  padding: 40px 24px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.upload-zone:hover,
.upload-zone.drag-over {
  border-color: #C9A84C;
  background: rgba(201, 168, 76, 0.04);
}

.upload-icon {
  font-size: 32px;
}

.upload-label {
  color: #64748b;
  font-size: 14px;
}

.upload-filename {
  color: #C9A84C;
  font-size: 13px;
  font-weight: 500;
}

.hidden-file-input {
  display: none;
}

.upload-type-select {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.upload-type-btn {
  padding: 7px 16px;
  background: #1A2332;
  border: 1px solid #2A3A4A;
  border-radius: 20px;
  color: #94a3b8;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.upload-type-btn:hover {
  border-color: #C9A84C;
  color: #E2E8F0;
}

.upload-type-btn.active {
  background: rgba(201, 168, 76, 0.15);
  border-color: #C9A84C;
  color: #C9A84C;
}

/* Scenarios Mode */
.scenarios-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.scenario-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 16px;
  background: #1A2332;
  border: 1px solid #2A3A4A;
  border-radius: 10px;
  cursor: pointer;
  text-align: right;
  transition: border-color 0.2s, background 0.2s;
}

.scenario-card:hover {
  border-color: #C9A84C;
  background: rgba(201, 168, 76, 0.06);
}

.sc-icon {
  font-size: 22px;
}

.sc-label {
  font-size: 15px;
  font-weight: 600;
  color: #E2E8F0;
}

.sc-question {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}

/* ── Config Panel ──────────────────────────────────── */
.config-section {
  max-width: 720px;
  margin: 16px auto 0;
  padding: 0 24px;
}

.config-card {
  background: #1A2332;
  border: 1px solid #2A3A4A;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.config-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-row-inline {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.config-label {
  font-size: 14px;
  font-weight: 600;
  color: #94a3b8;
}

.config-value-display {
  color: #C9A84C;
}

/* Platform Select */
.platform-select {
  width: 100%;
}

.config-select {
  width: 100%;
  padding: 10px 14px;
  background: #0C1222;
  border: 1px solid #2A3A4A;
  border-radius: 8px;
  color: #E2E8F0;
  font-size: 14px;
  cursor: pointer;
  outline: none;
  text-align: right;
  direction: rtl;
  transition: border-color 0.2s;
}

.config-select:focus {
  border-color: #C9A84C;
}

/* Rounds Slider */
.slider-wrapper {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rounds-slider {
  width: 100%;
  accent-color: #C9A84C;
  cursor: pointer;
  height: 4px;
}

.slider-range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #475569;
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  width: 48px;
  height: 26px;
  background: #2A3A4A;
  border: none;
  border-radius: 13px;
  cursor: pointer;
  transition: background 0.3s;
  flex-shrink: 0;
  padding: 0;
}

.toggle-switch.on {
  background: #C9A84C;
}

.toggle-knob {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 20px;
  height: 20px;
  background: #E2E8F0;
  border-radius: 50%;
  transition: transform 0.3s;
}

.toggle-switch.on .toggle-knob {
  transform: translateX(-22px);
}

/* Quality Tiers */
.quality-tiers {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.tier-btn {
  flex: 1;
  min-width: 90px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 10px 12px;
  background: #0C1222;
  border: 1px solid #2A3A4A;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.tier-btn:hover {
  border-color: #C9A84C;
}

.tier-btn.active {
  background: rgba(201, 168, 76, 0.12);
  border-color: #C9A84C;
}

.tier-label {
  font-size: 14px;
  font-weight: 600;
  color: #E2E8F0;
}

.tier-desc {
  font-size: 11px;
  color: #64748b;
}

.tier-btn.active .tier-label {
  color: #C9A84C;
}

/* Modifiers */
.modifiers-list {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.modifier-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #94a3b8;
  cursor: pointer;
  user-select: none;
}

.modifier-checkbox {
  accent-color: #C9A84C;
  width: 15px;
  height: 15px;
  cursor: pointer;
}

/* ── Launch ────────────────────────────────────────── */
.launch-section {
  max-width: 720px;
  margin: 24px auto 0;
  padding: 0 24px;
}

.launch-btn {
  width: 100%;
  padding: 18px;
  background: linear-gradient(135deg, #C9A84C, #b8933a);
  color: #0C1222;
  border: none;
  border-radius: 10px;
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.1s;
  letter-spacing: 0.5px;
}

.launch-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}

.launch-btn:active:not(:disabled) {
  transform: translateY(0);
}

.launch-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(12, 18, 34, 0.3);
  border-top-color: #0C1222;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: middle;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Stats Row ─────────────────────────────────────── */
.stats-row {
  display: flex;
  justify-content: center;
  gap: 24px;
  padding: 48px 24px 32px;
  flex-wrap: wrap;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 16px 28px;
  background: #1A2332;
  border-radius: 10px;
  border: 1px solid #2A3A4A;
  min-width: 110px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #C9A84C;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
}

/* ── Recent Simulations ────────────────────────────── */
.recent-section {
  padding: 0 32px 64px;
  max-width: 900px;
  margin: 0 auto;
}

.section-title {
  font-size: 20px;
  font-weight: 600;
  color: #E2E8F0;
  margin: 0 0 16px;
}

.recent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.recent-card {
  padding: 16px;
  background: #1A2332;
  border-radius: 10px;
  border: 1px solid #2A3A4A;
  cursor: pointer;
  transition: border-color 0.2s;
}

.recent-card:hover {
  border-color: #C9A84C;
}

.recent-question {
  font-size: 15px;
  font-weight: 500;
  margin-bottom: 8px;
  line-height: 1.5;
  color: #E2E8F0;
}

.recent-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: #64748b;
}

.recent-date {
  font-size: 12px;
  color: #475569;
}

.recent-status {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.recent-status.completed { background: #064e3b; color: #6ee7b7; }
.recent-status.running   { background: #1e3a5f; color: #60a5fa; }
.recent-status.failed    { background: #7f1d1d; color: #fca5a5; }
.recent-status.pending   { background: #2d2a1f; color: #fbbf24; }

.recent-result {
  margin-top: 8px;
  font-size: 13px;
  color: #94a3b8;
}

/* ── Mobile ────────────────────────────────────────── */
@media (max-width: 600px) {
  .knesset-header {
    padding: 12px 16px;
  }

  .hero {
    padding: 40px 16px 24px;
  }

  .hero-title {
    font-size: 30px;
  }

  .input-section,
  .config-section,
  .launch-section {
    padding: 0 16px;
  }

  .stats-row {
    gap: 12px;
    padding: 32px 16px;
  }

  .stat-card {
    padding: 12px 18px;
    min-width: 80px;
  }

  .stat-value {
    font-size: 22px;
  }

  .recent-section {
    padding: 0 16px 48px;
  }

  .quality-tiers {
    flex-direction: column;
  }

  .tier-btn {
    flex-direction: row;
    justify-content: space-between;
  }

  .scenarios-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
