<template>
  <div class="knesset-history" dir="rtl">
    <!-- Header -->
    <header class="history-header">
      <div class="brand" @click="$router.push('/')">MIROFISH</div>
      <div class="header-center">
        <h2>הצעות חוק</h2>
      </div>
      <div class="header-controls">
        <button class="btn-outline" @click="$router.push('/knesset')">חזרה</button>
      </div>
    </header>

    <main class="history-main">
      <!-- Search & Filters -->
      <div class="filters-row">
        <div class="search-box">
          <input
            v-model="searchQuery"
            type="text"
            class="search-input"
            placeholder="חיפוש הצעות חוק..."
            @input="debouncedSearch"
          />
        </div>
        <div class="filter-chips">
          <button
            v-for="status in statuses"
            :key="status.value"
            class="filter-chip"
            :class="{ active: activeStatus === status.value }"
            @click="toggleStatus(status.value)"
          >
            {{ status.label }}
          </button>
        </div>
      </div>

      <!-- Loading -->
      <div class="loading-state" v-if="loading">
        <div class="spinner"></div>
        <span>טוען...</span>
      </div>

      <!-- Bills List -->
      <div class="bills-list" v-else>
        <div
          v-for="bill in filteredBills"
          :key="bill.id"
          class="bill-card"
          @click="selectBill(bill)"
        >
          <div class="bill-main">
            <div class="bill-title">{{ bill.title_he }}</div>
            <div class="bill-meta">
              <span class="bill-status" :class="bill.status">{{ statusLabel(bill.status) }}</span>
              <span class="bill-date" v-if="bill.date">{{ bill.date }}</span>
              <span class="bill-proposer" v-if="bill.proposer">{{ bill.proposer }}</span>
            </div>
          </div>
          <div class="bill-votes" v-if="bill.votes_for != null">
            <span class="bv-for">{{ bill.votes_for }}</span>
            <span class="bv-sep">/</span>
            <span class="bv-against">{{ bill.votes_against }}</span>
          </div>
        </div>

        <div class="empty-state" v-if="!filteredBills.length && !loading">
          לא נמצאו הצעות חוק
        </div>
      </div>
    </main>

    <!-- Bill Detail Drawer -->
    <div class="detail-overlay" v-if="selectedBill" @click.self="selectedBill = null">
      <div class="detail-drawer">
        <div class="drawer-header">
          <h3>{{ selectedBill.title_he }}</h3>
          <button class="drawer-close" @click="selectedBill = null">✕</button>
        </div>
        <div class="drawer-body">
          <!-- Status -->
          <div class="detail-row">
            <span class="detail-label">סטטוס</span>
            <span class="bill-status" :class="selectedBill.status">{{ statusLabel(selectedBill.status) }}</span>
          </div>

          <!-- Proposer -->
          <div class="detail-row" v-if="selectedBill.proposer">
            <span class="detail-label">מציע</span>
            <span>{{ selectedBill.proposer }}</span>
          </div>

          <!-- Date -->
          <div class="detail-row" v-if="selectedBill.date">
            <span class="detail-label">תאריך</span>
            <span>{{ selectedBill.date }}</span>
          </div>

          <!-- Summary -->
          <div class="detail-section" v-if="selectedBill.summary_he">
            <h4>תקציר</h4>
            <p>{{ selectedBill.summary_he }}</p>
          </div>

          <!-- Vote Breakdown -->
          <div class="detail-section" v-if="selectedBill.vote_breakdown?.length">
            <h4>פילוח הצבעה</h4>
            <div class="breakdown-list">
              <div v-for="(fb, i) in selectedBill.vote_breakdown" :key="i" class="breakdown-row">
                <span class="breakdown-faction">{{ fb.faction }}</span>
                <span class="breakdown-for">{{ fb.for }}</span>
                <span class="breakdown-sep">/</span>
                <span class="breakdown-against">{{ fb.against }}</span>
              </div>
            </div>
          </div>

          <!-- Simulate Button -->
          <button class="btn-simulate" @click="simulateBill(selectedBill)">
            הדמה מחדש
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listBills } from '../../api/knesset'

const router = useRouter()
const bills = ref([])
const loading = ref(true)
const searchQuery = ref('')
const activeStatus = ref(null)
const selectedBill = ref(null)

let debounceTimer = null

const statuses = [
  { value: 'passed', label: 'אושרה' },
  { value: 'failed', label: 'נדחתה' },
  { value: 'pending', label: 'בדיון' },
  { value: 'withdrawn', label: 'נמשכה' }
]

const filteredBills = computed(() => {
  let result = bills.value
  if (activeStatus.value) {
    result = result.filter(b => b.status === activeStatus.value)
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    result = result.filter(b =>
      b.title_he?.toLowerCase().includes(q) ||
      b.proposer?.toLowerCase().includes(q) ||
      b.summary_he?.toLowerCase().includes(q)
    )
  }
  return result
})

function statusLabel(status) {
  const map = { passed: 'אושרה', failed: 'נדחתה', pending: 'בדיון', withdrawn: 'נמשכה' }
  return map[status] || status
}

function toggleStatus(val) {
  activeStatus.value = activeStatus.value === val ? null : val
}

function debouncedSearch() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => fetchBills(), 300)
}

function selectBill(bill) {
  selectedBill.value = bill
}

function simulateBill(bill) {
  router.push({ name: 'KnessetSimulate', query: { q: bill.title_he } })
}

async function fetchBills() {
  loading.value = true
  try {
    const params = {}
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    if (activeStatus.value) params.status = activeStatus.value
    const res = await listBills(params)
    if (res?.data?.bills) {
      bills.value = res.data.bills
    } else if (Array.isArray(res?.data)) {
      bills.value = res.data
    }
  } catch (e) {
    console.error('Failed to load bills:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchBills()
})
</script>

<style scoped>
.knesset-history {
  min-height: 100vh;
  background: #0f1117;
  color: #e5e7eb;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

/* Header */
.history-header {
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
.history-header h2 {
  font-size: 16px;
  margin: 0;
  font-weight: 500;
  color: #9ca3af;
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

/* Main */
.history-main {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
}

/* Filters */
.filters-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 24px;
}
.search-box {
  width: 100%;
}
.search-input {
  width: 100%;
  padding: 12px 16px;
  background: #1f2937;
  border: 1px solid #374151;
  border-radius: 8px;
  color: #e5e7eb;
  font-size: 15px;
  outline: none;
  text-align: right;
  box-sizing: border-box;
}
.search-input:focus {
  border-color: #60a5fa;
}
.search-input::placeholder {
  color: #6b7280;
}
.filter-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-chip {
  padding: 6px 14px;
  background: #1f2937;
  border: 1px solid #374151;
  border-radius: 16px;
  color: #9ca3af;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.filter-chip:hover {
  background: #374151;
  color: #e5e7eb;
}
.filter-chip.active {
  background: #3b82f6;
  border-color: #3b82f6;
  color: white;
}

/* Loading */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 80px 0;
  color: #6b7280;
}
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid #374151;
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Bills List */
.bills-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bill-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: #1a1d27;
  border: 1px solid #1f2937;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s;
  gap: 16px;
}
.bill-card:hover {
  border-color: #374151;
}
.bill-main {
  flex: 1;
  min-width: 0;
}
.bill-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 6px;
  line-height: 1.5;
}
.bill-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #6b7280;
}
.bill-status {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
.bill-status.passed { background: #064e3b; color: #6ee7b7; }
.bill-status.failed { background: #7f1d1d; color: #fca5a5; }
.bill-status.pending { background: #1e3a5f; color: #60a5fa; }
.bill-status.withdrawn { background: #374151; color: #9ca3af; }
.bill-votes {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}
.bv-for { color: #6ee7b7; }
.bv-against { color: #fca5a5; }
.bv-sep { color: #4b5563; }

.empty-state {
  text-align: center;
  padding: 60px 0;
  color: #4b5563;
  font-size: 15px;
}

/* Detail Drawer */
.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  justify-content: flex-start;
  z-index: 100;
}
.detail-drawer {
  width: 480px;
  max-width: 90vw;
  height: 100vh;
  background: #1a1d27;
  border-left: 1px solid #374151;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #1f2937;
}
.drawer-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.5;
}
.drawer-close {
  background: none;
  border: none;
  color: #6b7280;
  font-size: 18px;
  cursor: pointer;
}
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.detail-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.detail-label {
  font-size: 13px;
  color: #6b7280;
  min-width: 60px;
}
.detail-section {
  margin-top: 20px;
}
.detail-section h4 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 8px;
  color: #9ca3af;
}
.detail-section p {
  font-size: 14px;
  line-height: 1.7;
  color: #d1d5db;
  margin: 0;
}
.breakdown-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.breakdown-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #111318;
  border-radius: 4px;
  font-size: 13px;
}
.breakdown-faction {
  flex: 1;
}
.breakdown-for { color: #6ee7b7; }
.breakdown-against { color: #fca5a5; }
.breakdown-sep { color: #4b5563; }

.btn-simulate {
  margin-top: 24px;
  width: 100%;
  padding: 12px;
  background: #3b82f6;
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-simulate:hover {
  background: #2563eb;
}
</style>
