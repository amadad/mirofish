<template>
  <div class="coalition-graph" dir="rtl">
    <h3>דינמיקת קואליציה</h3>
    <div v-if="cytoscapeAvailable" ref="cyContainer" class="cy-container"></div>
    <div v-else class="fallback-list">
      <div v-for="f in factions" :key="f.name" class="fallback-item" :class="f.side">
        <span class="fallback-name">{{ f.name }}</span>
        <span class="fallback-seats">{{ f.seats }} מנדטים</span>
      </div>
    </div>
    <div class="legend">
      <span class="dot coalition"></span> קואליציה
      <span class="dot opposition"></span> אופוזיציה
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, shallowRef, nextTick } from 'vue'

const props = defineProps({
  factions: { type: Array, default: () => [] },
  relationships: { type: Array, default: () => [] }
})

const cyContainer = ref(null)
const cy = shallowRef(null)
const cytoscapeAvailable = ref(true)
let cytoscape = null

function buildElements() {
  const nodes = props.factions.map(f => ({
    data: {
      id: f.name,
      label: `${f.name}\n(${f.seats})`,
      seats: f.seats,
      side: f.side
    }
  }))
  const edges = props.relationships.map((r, i) => ({
    data: {
      id: `e${i}`,
      source: r.source,
      target: r.target,
      type: r.type,
      strength: r.strength || 1
    }
  }))
  return [...nodes, ...edges]
}

function buildStyle() {
  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        'text-wrap': 'wrap',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': '10px',
        color: '#fff',
        'text-outline-color': '#333',
        'text-outline-width': 1,
        width: 'mapData(seats, 4, 35, 30, 80)',
        height: 'mapData(seats, 4, 35, 30, 80)'
      }
    },
    {
      selector: 'node[side="coalition"]',
      style: { 'background-color': '#2563eb' }
    },
    {
      selector: 'node[side="opposition"]',
      style: { 'background-color': '#dc2626' }
    },
    {
      selector: 'edge',
      style: {
        width: 'mapData(strength, 0, 10, 1, 6)',
        'line-color': '#94a3b8',
        'curve-style': 'bezier',
        opacity: 0.6
      }
    }
  ]
}

async function initGraph() {
  if (!cyContainer.value) return
  try {
    const mod = await import('cytoscape')
    cytoscape = mod.default || mod
  } catch {
    cytoscapeAvailable.value = false
    return
  }

  cy.value = cytoscape({
    container: cyContainer.value,
    elements: buildElements(),
    style: buildStyle(),
    layout: {
      name: 'cose',
      animate: true,
      animationDuration: 500,
      nodeRepulsion: 6000,
      idealEdgeLength: 120,
      gravity: 0.3,
      padding: 20
    },
    userZoomingEnabled: true,
    userPanningEnabled: true
  })
}

function updateGraph() {
  if (!cy.value) return
  cy.value.elements().remove()
  cy.value.add(buildElements())
  cy.value.layout({
    name: 'cose',
    animate: true,
    animationDuration: 300,
    nodeRepulsion: 6000,
    idealEdgeLength: 120,
    gravity: 0.3,
    padding: 20
  }).run()
}

watch(() => [props.factions, props.relationships], () => {
  if (cy.value) updateGraph()
}, { deep: true })

onMounted(async () => {
  await nextTick()
  initGraph()
})

onBeforeUnmount(() => {
  if (cy.value) {
    cy.value.destroy()
    cy.value = null
  }
})
</script>

<style scoped>
.coalition-graph {
  padding: 16px;
}

.coalition-graph h3 {
  margin: 0 0 12px;
  font-size: 18px;
}

.cy-container {
  width: 100%;
  height: 400px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
}

.legend {
  margin-top: 8px;
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 14px;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
}

.dot.coalition {
  background: #2563eb;
}

.dot.opposition {
  background: #dc2626;
}

/* Fallback list when cytoscape is not available */
.fallback-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 16px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  min-height: 120px;
}

.fallback-item {
  padding: 8px 12px;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  display: flex;
  gap: 8px;
  align-items: center;
}

.fallback-item.coalition {
  background: #2563eb;
}

.fallback-item.opposition {
  background: #dc2626;
}

.fallback-seats {
  opacity: 0.85;
  font-size: 12px;
}
</style>
