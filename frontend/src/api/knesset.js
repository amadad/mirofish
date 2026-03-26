import service, { requestWithRetry } from './index'

/**
 * Run a Knesset simulation
 * @param {string} questionHe - The legislative question in Hebrew
 * @param {number} rounds - Number of debate rounds (default 5)
 * @param {string|null} scenario - Optional scenario type
 * @param {Object} options - { platform, socialLayer, modifiers }
 */
export const runSimulation = (questionHe, rounds = 5, scenario = null, options = {}) => {
  const { platform = 'plenum', socialLayer = true, modifiers = [] } = options
  const data = { question_he: questionHe, rounds, platform, social_layer: socialLayer, modifiers }
  if (scenario) data.scenario = scenario
  return requestWithRetry(() => service.post('/api/knesset/simulate', data), 3, 1000)
}

/**
 * List available simulation platforms
 */
export const listPlatforms = () => {
  return service.get('/api/knesset/platforms')
}

/**
 * Inject an event into a running simulation
 * @param {string} simId - Active simulation ID
 * @param {string} eventHe - Event text in Hebrew
 * @param {string} source - Source type (default 'manual')
 */
export const injectEvent = (simId, eventHe, source = 'manual') => {
  return service.post('/api/knesset/inject', { simulation_id: simId, event_he: eventHe, source })
}

/**
 * Get simulation status/results
 * @param {string} simId - Simulation ID
 */
export const getSimulationStatus = (simId) => {
  return service.get(`/api/knesset/simulate/${simId}`)
}

/**
 * Query historical Knesset data
 * @param {string} questionHe - Search query in Hebrew
 */
export const queryHistory = (questionHe) => {
  return service.post('/api/knesset/history/query', { question_he: questionHe })
}

/**
 * List MKs with optional filters
 * @param {Object} params - { faction?, active?, limit?, offset? }
 */
export const listMKs = (params = {}) => {
  return service.get('/api/knesset/mks', { params })
}

/**
 * Get MK detail
 * @param {string} mkId - MK identifier
 */
export const getMKDetail = (mkId) => {
  return service.get(`/api/knesset/mks/${mkId}`)
}

/**
 * Chat with one or more MK agents
 * @param {string[]} mkIds - Array of MK identifiers
 * @param {string} messageHe - Message in Hebrew
 */
export const chatWithMK = (mkIds, messageHe) => {
  return requestWithRetry(
    () => service.post('/api/knesset/mks/chat', { mk_ids: mkIds, message_he: messageHe }),
    3, 1000
  )
}

/**
 * List all factions
 */
export const listFactions = () => {
  return service.get('/api/knesset/factions')
}

/**
 * List bills with optional filters
 * @param {Object} params - { status?, faction?, search?, limit?, offset? }
 */
export const listBills = (params = {}) => {
  return service.get('/api/knesset/bills', { params })
}

/**
 * Run a predefined scenario
 * @param {string} type - Scenario type (e.g. 'coalition_crisis', 'budget_vote')
 * @param {Object} params - Scenario-specific parameters
 */
export const runScenario = (type, params) => {
  return requestWithRetry(
    () => service.post('/api/knesset/scenarios/run', { type, ...params }),
    3, 1000
  )
}

/**
 * Get Knesset stats (MK count, factions, bills, simulations)
 */
export const getStats = () => {
  return service.get('/api/knesset/stats')
}

// ============== Claude Analysis Chat ==============

/**
 * Chat with Claude about simulation analysis
 * @param {string} messageHe - User message in Hebrew
 * @param {string|null} simulationId - Active simulation ID
 * @param {string|null} sessionId - Existing chat session ID
 * @param {Object|null} simulationState - Direct state override
 */
export const claudeChat = (messageHe, simulationId = null, sessionId = null, simulationState = null) => {
  return requestWithRetry(
    () => service.post('/api/knesset/claude/chat', {
      message_he: messageHe,
      simulation_id: simulationId,
      session_id: sessionId,
      simulation_state: simulationState,
    }),
    2, 1000
  )
}

// ============== Profile Cache ==============

/**
 * Pre-generate and cache all profiles for a graph
 * @param {string} graphId - Graph ID to warm cache for
 */
export const warmProfilesCache = (graphId) => {
  return service.post('/api/knesset/profiles/warm', { graph_id: graphId })
}

/**
 * Invalidate cached profiles
 * @param {string|null} entityUuid - Specific entity to invalidate, or null for all
 */
export const invalidateProfilesCache = (entityUuid = null) => {
  return service.post('/api/knesset/profiles/invalidate', { entity_uuid: entityUuid })
}

// ============== Live Data Feed ==============

/**
 * Inject a manual political event into the live feed
 * @param {string} titleHe - Event title in Hebrew
 * @param {string} contentHe - Event content in Hebrew
 * @param {string} eventType - Event type (manual, bill, vote, news)
 * @param {string} impact - Impact level (high, medium, low)
 */
export const injectLiveEvent = (titleHe, contentHe = '', eventType = 'manual', impact = 'high') => {
  return service.post('/api/knesset/live-feed/inject', {
    title_he: titleHe,
    content_he: contentHe,
    event_type: eventType,
    impact,
  })
}

/**
 * Get recent live feed events
 * @param {number} limit - Max events to return
 */
export const getLiveFeedEvents = (limit = 20) => {
  return service.get('/api/knesset/live-feed/events', { params: { limit } })
}
