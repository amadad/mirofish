import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true
  },
  // --- Knesset Simulator ---
  {
    path: '/knesset',
    name: 'KnessetHome',
    component: () => import('../views/knesset/KnessetHome.vue')
  },
  {
    path: '/knesset/simulate',
    name: 'KnessetSimulate',
    component: () => import('../views/knesset/KnessetSimulate.vue')
  },
  {
    path: '/knesset/simulate/:simId',
    name: 'KnessetResults',
    component: () => import('../views/knesset/KnessetResults.vue'),
    props: true
  },
  {
    path: '/knesset/mk/:mkId',
    name: 'KnessetMKDetail',
    component: () => import('../views/knesset/KnessetMKDetail.vue'),
    props: true
  },
  {
    path: '/knesset/history',
    name: 'KnessetHistory',
    component: () => import('../views/knesset/KnessetHistory.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
