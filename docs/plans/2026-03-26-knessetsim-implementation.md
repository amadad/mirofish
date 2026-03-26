# KnessetSim Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform MiroFish Knesset module into a full Command Center UI with 8 simulation modes, Social Layer, tycoon agents, and Backend tab.

**Architecture:** Vue 3 frontend (no Tailwind, vanilla CSS, RTL) with Flask backend. All backend platforms already built. This plan focuses on: (1) remaining backend pieces, (2) frontend Command Center redesign, (3) wiring everything together.

**Tech Stack:** Vue 3 + Vite + D3.js (installed), Flask, KuzuDB, SQLite, Groq/Claude CLI

**Design spec:** `docs/plans/2026-03-25-knessetsim-full-spec.md`

---

## Task 1: Press Conference Platform (Backend)

**Files:**
- Create: `backend/app/services/knesset/platforms/press_conference.py`
- Modify: `backend/app/services/knesset/platforms/__init__.py`
- Modify: `backend/app/services/knesset/orchestrator.py` (add to `_get_platform`)

**Step 1: Create press_conference.py**

Platform where MKs and journalists interact in Q&A format.

```python
PLATFORM_ID = "press_conference"
ACTIONS = ["ASK", "ANSWER", "FOLLOW_UP", "DEFLECT", "NO_COMMENT", "CHALLENGE"]
```

State: `questions_asked`, `answers_given`, `follow_ups`, `deflections`
Turn logic: journalists ASK, MKs ANSWER/DEFLECT/NO_COMMENT. Journalists can FOLLOW_UP or CHALLENGE.
Prompt: Hebrew, shows podium context + recent Q&A.

Follow the pattern of `roundtable.py` — same imports, same structure, ~180 lines.

**Step 2: Register in __init__.py and orchestrator.py**

Add `PressConferencePlatform` to `PLATFORM_REGISTRY` and `_get_platform()`.

**Step 3: Verify syntax**

```bash
cd MIROFISH/backend && python -c "import ast; ast.parse(open('app/services/knesset/platforms/press_conference.py', encoding='utf-8').read()); print('OK')"
```

---

## Task 2: Tycoon & Activist Agent Rosters (Backend)

**Files:**
- Modify: `backend/app/services/knesset/persona_generator.py`
- Modify: `backend/app/services/knesset/types.py` (add TYCOON_ACTIONS, ACTIVIST_ACTIONS)

**Step 1: Add tycoon-specific actions to types.py**

```python
TYCOON_ACTIONS: List[str] = [
    "ECONOMIC_PRESSURE",   # איום כלכלי
    "THREATEN_RELOCATION", # איום העברת פעילות
    "LOBBY",               # שכנוע פרטי
    "PUBLIC_STATEMENT",    # הצהרה פומבית
    "DO_NOTHING",
]

ACTIVIST_ACTIONS: List[str] = [
    "PROTEST",             # הפגנה
    "PETITION",            # עצומה
    "PUBLIC_PRESSURE",     # לחץ ציבורי
    "SPEAK_IN_PLENUM",     # נאום (אם מוזמן)
    "DO_NOTHING",
]
```

**Step 2: Add tycoon roster to persona_generator.py**

Add method `generate_tycoon_personas()` with 8-12 hardcoded Israeli tycoons:
- נוחי דנקנר (נדל"ן/תעשייה), שרי אריסון (בנקאות), מוטי בן משה (תקשורת), אלפרד אקירוב (נדל"ן), צדיק בינו (אנרגיה), יצחק תשובה (אנרגיה/נדל"ן), ארנון מילצ'ן (תקשורת), עידן עופר (ספנות/כימיקלים)

Each with: name_he, name_en, role="tycoon", sector, influence_score, stances, personality.

**Step 3: Add activist roster**

Add method `generate_activist_personas()` with 4-6 hardcoded activists:
- Representatives from protest movements, rights organizations, settlement councils, social justice.

**Step 4: Verify syntax**

```bash
cd MIROFISH/backend && python -c "import ast; ast.parse(open('app/services/knesset/types.py', encoding='utf-8').read()); print('OK')"
```

---

## Task 3: Social Layer Engine (Backend)

**Files:**
- Create: `backend/app/services/knesset/social_layer.py`
- Modify: `backend/app/services/knesset/knesset_loop.py` (integrate social layer after each round)

**Step 1: Create social_layer.py (~200 lines)**

```python
class SocialLayer:
    """Twitter-like overlay that runs after each KnessetLoop round.

    Agents who took notable actions have a chance to tweet about it.
    Other agents can RT/LIKE/REPLY.
    """

    def __init__(self, router, personas, auxiliary_agents=None):
        self.router = router
        self.personas = personas
        self.auxiliary_agents = auxiliary_agents or []
        self.tweets: List[dict] = []  # {agent_id, agent_name, content, likes, rts, replies, round}
        self.engagement_log: List[dict] = []

    async def process_round(self, round_num, round_actions) -> List[dict]:
        """After a KnessetLoop round, generate social media reactions."""
        new_tweets = []

        # 1. Agents who acted might tweet (40% chance)
        for action in round_actions:
            if action.action_type == "DO_NOTHING":
                continue
            if random.random() < 0.4:
                tweet = await self._generate_tweet(action, round_num)
                new_tweets.append(tweet)

        # 2. Journalists always tweet analysis (if present)
        for journalist in self._get_journalists():
            tweet = await self._generate_journalist_tweet(journalist, round_actions, round_num)
            new_tweets.append(tweet)

        # 3. Tycoons react if their sector is affected
        for tycoon in self._get_tycoons():
            if self._is_sector_affected(tycoon, round_actions):
                tweet = await self._generate_tycoon_tweet(tycoon, round_actions, round_num)
                new_tweets.append(tweet)

        # 4. Generate engagement (likes, RTs) on existing tweets
        engagement = self._simulate_engagement(new_tweets)

        self.tweets.extend(new_tweets)
        self.engagement_log.extend(engagement)
        return new_tweets

    def get_trending(self) -> List[str]:
        """Extract trending hashtags from tweets."""

    def get_engagement_stats(self) -> dict:
        """Return total engagement metrics."""

    def get_influence_adjustments(self) -> Dict[str, float]:
        """Agents with high engagement get temporary influence boost."""
```

**Step 2: Wire into knesset_loop.py**

In `KnessetLoop.__init__`, accept optional `social_layer` parameter.
After `run_round()` completes, if social_layer is set, call `social_layer.process_round()`.
Append social tweets to the round summary.

**Step 3: Wire into orchestrator.py**

When simulation config has `social_layer: true`, create `SocialLayer` and pass to `KnessetLoop`.

**Step 4: Add API response field**

In round summary, include `social_tweets` array alongside actions.

**Step 5: Verify syntax**

---

## Task 4: API — Platform Parameter in Simulate Endpoint

**Files:**
- Modify: `frontend/src/api/knesset.js`

**Step 1: Update runSimulation to accept platform + config**

```javascript
export async function runSimulation(questionHe, options = {}) {
  const { rounds = 5, scenario = null, platform = 'plenum', socialLayer = true, modifiers = [] } = options
  const response = await api.post('/api/knesset/simulate', {
    question_he: questionHe,
    rounds,
    scenario,
    platform,
    social_layer: socialLayer,
    modifiers,
  })
  return response.data
}
```

**Step 2: Add new API functions**

```javascript
export async function listPlatforms() {
  const response = await api.get('/api/knesset/platforms')
  return response.data
}

export async function injectEvent(simId, eventHe, source = 'manual') {
  const response = await api.post('/api/knesset/inject', {
    simulation_id: simId,
    event_he: eventHe,
    source,
  })
  return response.data
}
```

---

## Task 5: Frontend — Command Center Layout

**Files:**
- Rewrite: `frontend/src/views/KnessetSimulate.vue`
- Modify: `frontend/src/App.vue` (add persistent nav for knesset routes)

**Step 1: Create Command Center layout in KnessetSimulate.vue**

Replace the current 2-panel layout with the Command Center:

```
┌─ Header ────────────────────────────────────────────┐
│ 🕎 סימולטור הכנסת │ Current scenario │ Status │ 💬  │
├─ Tabs ──────────────────────────────────────────────┤
│ 🏛️ מליאה │ 🪑 ועדה │ 👥 ח"כים │ 📊 קואליציה │ ... │
├─────────────────────────────┬───────────────────────┤
│  MAIN STAGE (75%)           │  AI PANEL (25%)       │
│  (component changes by tab) │  (ClaudeChatPanel)    │
├─────────────────────────────┤                       │
│  LIVE FEED (bottom 20%)     │                       │
│  (PlenumFeed)               │                       │
└─────────────────────────────┴───────────────────────┘
```

Key implementation:
- Use Vue `<component :is="currentMainComponent">` for tab switching
- `currentMainComponent` maps tab → component (HemicycleChart, RoundtableView, etc.)
- AI Panel always visible (ClaudeChatPanel)
- Live Feed always visible (PlenumFeed, extended with social tweets)
- Tabs: computed from available platforms + utility tabs (ח"כים, קואליציה, חוקים, Backend)

**Step 2: Dark Knesset theme CSS**

```css
:root {
  --knesset-bg: #0C1222;
  --knesset-surface: #1A2332;
  --knesset-border: #2A3A4A;
  --knesset-text: #E2E8F0;
  --knesset-gold: #C9A84C;
  --knesset-coalition: #2563EB;
  --knesset-opposition: #DC2626;
  --knesset-vote-for: #16A34A;
  --knesset-vote-against: #DC2626;
  --knesset-vote-abstain: #F59E0B;
}
```

**Step 3: Wire tab navigation**

Each tab sets `activeTab` which maps to a component:
- `plenum` → HemicycleChart + VoteTally
- `committee` → RoundtableView
- `mks` → MK browser grid
- `coalition` → CoalitionGraph
- `bills` → Bill list
- `twitter` → TwitterFeed (new component)
- `backend` → BackendPanel (new component)

---

## Task 6: Frontend — Interactive Hemicycle Upgrade

**Files:**
- Rewrite: `frontend/src/components/knesset/HemicycleChart.vue`

**Step 1: Upgrade from CSS circles to D3.js SVG hemicycle**

Current: CSS absolute-positioned colored circles in 7 rows.
Target: D3.js SVG with:
- Proper hemicycle arc layout (seats positioned on concentric arcs)
- Each seat is clickable → emits `@select-mk` event
- Real-time color updates: gray (no vote) → green/red/orange
- Hover tooltip: MK name + faction
- Faction grouping visible by position
- Speaker podium at center-bottom
- Current bill + vote progress bar at podium

Use D3 (already in package.json) for arc calculations and SVG rendering.

**Step 2: Add click-to-inspect**

When user clicks an MK seat:
- Emit event to parent (Command Center)
- Parent shows MK detail card overlay or switches AI Panel to MK interview mode

---

## Task 7: Frontend — Twitter Feed Component

**Files:**
- Create: `frontend/src/components/knesset/TwitterFeed.vue`

**Step 1: Create Twitter-style feed component**

Props: `tweets` (Array), `trending` (Array), `engagementStats` (Object)

Layout:
- Left (70%): Tweet cards — avatar, name, handle, content, engagement counts (❤️ 🔄 💬)
- Right (30%): Trending sidebar + engagement analytics

Styling: Dark theme matching Twitter/X aesthetic but with Knesset colors.

---

## Task 8: Frontend — Backend Panel Component

**Files:**
- Create: `frontend/src/components/knesset/BackendPanel.vue`

**Step 1: Create the "Behind the Scenes" tab**

Shows:
1. Pipeline status — 5-step progress bar
2. Knowledge graph — embed GraphPanel.vue (already exists!)
3. Decision log — scrollable raw action log
4. Model routing — tier breakdown table
5. Cost tracker — running total
6. Agent memory — episode count, top alliances/rivalries

Props: `simulationState` (Object), `pipelineStatus` (Object)

Reuse existing `GraphPanel.vue` component for the knowledge graph section.

---

## Task 9: Frontend — Configure Simulation Panel

**Files:**
- Rewrite: `frontend/src/views/KnessetHome.vue`

**Step 1: Redesign landing page**

Three input channels:
1. Free text: "מה תרצה לבדוק?" input field
2. Document upload: drag-and-drop zone with type selector (הצעת חוק / פרוטוקול / נתונים / כתבה)
3. Quick scenarios: preset cards

Below: Configuration panel
- Platform dropdown (8 modes with Hebrew labels)
- Rounds slider (1-50)
- Participant filter (all / faction / committee / custom)
- Social Layer toggle
- Modifiers checkboxes (משבר ביטחוני, ח"כ עוזב, בחירות)
- Quality tier selector (Economy / Standard / Premium)

Big "🚀 הפעל סימולציה" button.

**Step 2: Wire to API**

On submit → call `runSimulation()` with all params → navigate to `/knesset/simulate?simId=...`

---

## Task 10: Frontend — MK Browser Tab

**Files:**
- Create: `frontend/src/components/knesset/MKBrowser.vue`

**Step 1: Create grid of all 120 MKs**

- Filterable by faction, coalition/opposition, influence score
- Search by name
- Each MK card shows: avatar (initial), name, faction color bar, influence score, coalition badge
- Click → opens MK detail (interview in AI Panel)

Uses existing `MKCard.vue` component in a CSS grid.

---

## Task 11: Frontend — Event Injection UI

**Files:**
- Modify: `frontend/src/components/knesset/PlenumFeed.vue`

**Step 1: Add injection input at top of feed**

```html
<div class="inject-bar" v-if="isRunning">
  <input v-model="injectText" placeholder="הזרק אירוע חי..." />
  <button @click="injectEvent">⚡ הזרק</button>
</div>
```

Calls `injectEvent(simId, injectText)` API function.

---

## Task 12: Wire Everything Together

**Files:**
- Modify: `frontend/src/router/index.js` (add any missing routes)
- Modify: `frontend/src/views/KnessetSimulate.vue` (import all new components)
- Modify: `backend/app/api/knesset.py` (add social_layer + modifiers to simulate endpoint)

**Step 1: Update simulate API to accept social_layer and modifiers**

```python
social_layer_enabled = data.get('social_layer', True)
modifiers = data.get('modifiers', [])
```

Pass to orchestrator. Orchestrator applies modifiers via existing `scenarios.py`.

**Step 2: Import all components in KnessetSimulate.vue**

```javascript
import HemicycleChart from '../components/knesset/HemicycleChart.vue'
import RoundtableView from '../components/knesset/RoundtableView.vue'
import NegotiationView from '../components/knesset/NegotiationView.vue'
import BrainstormView from '../components/knesset/BrainstormView.vue'
import DecisionView from '../components/knesset/DecisionView.vue'
import TwitterFeed from '../components/knesset/TwitterFeed.vue'
import BackendPanel from '../components/knesset/BackendPanel.vue'
import MKBrowser from '../components/knesset/MKBrowser.vue'
import CoalitionGraph from '../components/knesset/CoalitionGraph.vue'
import ClaudeChatPanel from '../components/knesset/ClaudeChatPanel.vue'
import PlenumFeed from '../components/knesset/PlenumFeed.vue'
```

**Step 3: Tab-to-component mapping**

```javascript
const tabComponents = {
  plenum: HemicycleChart,
  committee: RoundtableView,
  negotiation: NegotiationView,
  brainstorm: BrainstormView,
  decision: DecisionView,
  press: PressConferenceView,
  twitter: TwitterFeed,
  mks: MKBrowser,
  coalition: CoalitionGraph,
  backend: BackendPanel,
}
```

**Step 4: Verify dev server runs**

```bash
cd MIROFISH/frontend && npm run dev
```

Open http://localhost:3000/knesset — verify Command Center loads.

---

## Execution Priority

| Task | Priority | Effort | Dependencies |
|------|----------|--------|-------------|
| 1. Press Conference Platform | HIGH | 2h | None |
| 2. Tycoon & Activist Rosters | HIGH | 2h | None |
| 3. Social Layer Engine | HIGH | 3h | Task 2 |
| 4. API Updates | HIGH | 1h | None |
| 5. Command Center Layout | **CRITICAL** | 4h | Task 4 |
| 6. Interactive Hemicycle | **CRITICAL** | 3h | Task 5 |
| 7. Twitter Feed Component | HIGH | 2h | Task 5 |
| 8. Backend Panel | MEDIUM | 2h | Task 5 |
| 9. Configure Panel (Home) | HIGH | 3h | Task 4 |
| 10. MK Browser | MEDIUM | 2h | Task 5 |
| 11. Event Injection UI | MEDIUM | 1h | Task 5 |
| 12. Wire Everything | **CRITICAL** | 2h | Tasks 1-11 |

**Parallel execution possible:** Tasks 1+2+4 (backend, no deps) → Tasks 3+5+9 → Tasks 6+7+8+10+11 → Task 12

**Total estimated effort: ~27 hours**
