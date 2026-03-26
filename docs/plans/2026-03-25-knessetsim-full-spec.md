# KnessetSim — Full Product Specification

> **Date**: 2026-03-25
> **Status**: Approved design — ready for implementation planning
> **Base**: MiroFish fork (amadad/mirofish) + RZMAPPER data

---

## 1. Vision

A digital Knesset simulation platform where AI agents representing real Israeli politicians, journalists, tycoons, and lobbyists interact in parliamentary scenarios. The user doesn't use software — they enter the Knesset plenum.

**Core experience**: Type a bill or question in Hebrew → watch 120+ agents debate, vote, tweet, and negotiate in real-time → ask the AI parliamentary advisor anything.

---

## 2. The Main Screen — "The Digital Plenum Hall"

### 2.1 Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  🕎  סימולטור הכנסת  │  כנסת ה-25  │  ● סימולציה פעילה  │  💬 יועץ │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                         HEMICYCLE                                   │
│               ╭───┤   דוכן יו"ר הכנסת    ├───╮                     │
│          ╭────┤   ╰───────────────────────╯   ├────╮                │
│     ╭────┤  [coalition factions by seats]      ├────╮               │
│╭────┤                                         ├────╮              │
││ OPP│   ╭─ Current Bill + Vote Progress ──╮   │COAL│               │
││    │   │ סבב 3/5  │  בעד: 42  נגד: 58   │   │    │               │
││ 56 │   ╰─────────────────────────────────╯   │ 64 │               │
│╰────┤  [opposition factions by seats]         ├────╯               │
│     ╰────┤                               ├────╯                    │
│          ╰───────────────────────────────╯                          │
│                                                                     │
├──────────────────────────┬──────────────────────────────────────────┤
│  📜 Live Plenum Feed     │  🕎 Parliamentary Advisor (AI)           │
│  (actions, speeches,     │  Context-aware Hebrew chat               │
│   tweets, pressures)     │  Always visible, always relevant         │
└──────────────────────────┴──────────────────────────────────────────┘
```

### 2.2 Color Palette

| Element | Color | Hex |
|---------|-------|-----|
| Background | Dark navy | `#0C1222` |
| Coalition | Blue | `#2563EB` |
| Opposition | Red | `#DC2626` |
| Vote For | Green | `#16A34A` |
| Vote Against | Red | `#DC2626` |
| Abstain | Orange | `#F59E0B` |
| Text primary | Light gray | `#E2E8F0` |
| Accent (menorah) | Gold | `#C9A84C` |
| Fonts | Heebo (headers), Noto Sans Hebrew (body) | — |

### 2.3 Navigation Tabs

```
🏛️ מליאה │ 🪑 ועדה │ 👥 ח"כים │ 📊 קואליציה │ ⚡ תרחיש │
📋 חוקים │ 📰 מציאות │ 🐦 Twitter │ 🔧 Backend │ 💬 יועץ
```

---

## 3. User Flow

### 3.1 New User Flow

```
1. LANDING — "מה תרצה לבדוק היום?"
   ├── Quick scenario buttons (חוק הגיוס, תקציב, דיור...)
   ├── Free text input ("כתוב שאלה...")
   └── Upload document (הצעת חוק, פרוטוקול, נתונים)

2. CONFIGURE — Settings panel
   ├── Platform selector (8 modes)
   ├── Rounds slider (1-50)
   ├── Participant filter (all 120 / faction / committee / custom)
   ├── Modifiers (crisis, defection, elections...)
   ├── Layers (Social Layer on/off, journalists, tycoons)
   └── Quality tier (Economy / Standard / Premium)

3. LIVE SIMULATION — Main stage
   ├── Hemicycle with real-time votes
   ├── Live feed of actions
   ├── AI advisor available
   └── Can inject events mid-simulation

4. RESULTS — Analysis + "What now?"
   ├── Vote breakdown by faction
   ├── Key arguments
   ├── Swing MKs
   ├── "What would it take" analysis
   ├── → Run again with changes
   ├── → Switch platform (plenum → negotiation)
   ├── → Interview specific MK
   └── → Ask advisor
```

### 3.2 Difference from MiroFish Original

| MiroFish (5-step wizard) | KnessetSim |
|--------------------------|------------|
| Step 1: Upload docs — REQUIRED | Data already loaded. Upload is OPTIONAL enrichment |
| Step 2: Build ontology — WAIT | 120 personas always ready |
| Step 3: Run simulation — WAIT (subprocess) | Live view — see it happen |
| Step 4: Generate report — WAIT | Report builds during simulation + instant AI advisor |
| Step 5: Chat — only here | AI advisor ALWAYS available |
| **Total wait: ~10 min before first insight** | **~30 seconds to first vote** |

---

## 4. Eight Simulation Modes

### 4.1 Mode Table

| Mode | Agents | Rounds | Actions | Engine | Est. Cost |
|------|--------|--------|---------|--------|-----------|
| 🏛️ Plenum (Full) | 120 MKs | 3-10 | 8 parliamentary | KnessetLoop | ~$0.30 |
| 🪑 Committee | 9-15 | 4-12 | 6 (roundtable) | KnessetLoop | ~$0.05 |
| 🤝 Coalition Negotiation | 2-6 sides | 5-15 | 6 (negotiation) | KnessetLoop | ~$0.03 |
| 💡 Brainstorm | 8-20 | 4-8 | 6 (brainstorm) | KnessetLoop | ~$0.04 |
| 📊 Decision | 5-12 | 4-8 | 6 (decision) | KnessetLoop | ~$0.04 |
| 📰 Press Conference | 5-10 MKs + journalists | 3-8 | Q&A | KnessetLoop | ~$0.03 |
| 🐦 Twitter/X | 10-120 | 5-20 | 7 (OASIS) | OASIS subprocess | ~$0.50 |
| ⚙️ Custom | 1-150 | 1-50 | configurable | configurable | varies |

### 4.2 Platform Actions

**Plenum**: PROPOSE_BILL, VOTE, SPEAK_IN_PLENUM, LOBBY, FORM_ALLIANCE, DEFECT, AMEND_BILL, DO_NOTHING

**Roundtable (Committee)**: SPEAK, RESPOND, CHALLENGE, AGREE, PROPOSE, ABSTAIN

**Negotiation**: OFFER, COUNTER, CONCEDE, BLUFF, WALK_AWAY, ACCEPT

**Brainstorm**: IDEA, BUILD_ON, CRITIQUE, COMBINE, PRIORITIZE, VOTE (two-phase: divergent rounds 1-3, convergent 4+)

**Decision**: ANALYZE, ADVOCATE, DEVIL_ADVOCATE, VOTE, ABSTAIN, DEFER (three-phase: analyze 1-2, debate 3-4, vote 5+)

**Twitter (OASIS)**: CREATE_POST, LIKE_POST, REPOST, QUOTE_POST, REPLY, FOLLOW, DO_NOTHING

### 4.3 Social Layer

Twitter actions run as an overlay on ANY platform. When enabled:
- 40% chance an MK tweets about their action
- Other agents can RT/LIKE/REPLY
- Journalists tweet analysis
- Tycoons tweet reactions
- Engagement metrics feed back into influence_score

Toggle: `Social Layer: ☑️ ON` in simulation config.

---

## 5. Agent Types (6 Categories)

### 5.1 Agent Roster

| Type | Count | Source | Can Vote | Can Tweet | Special Ability |
|------|-------|--------|----------|-----------|-----------------|
| **MKs** | 120 | RZMAPPER + Knesset API | ✅ | ✅ | Full parliamentary powers |
| **Journalists** | 8-12 | Hardcoded roster | ❌ | ✅ | EXPOSE (reveal info), PRESSURE (public) |
| **Lobbyists** | 5-8 | Hardcoded roster | ❌ | ✅ | LOBBY (private persuasion), DEAL |
| **Tycoons/Industrialists** | 8-12 | Hardcoded roster | ❌ | ✅ | ECONOMIC_PRESSURE, THREATEN_RELOCATION |
| **Advisors** | 4-6 | Hardcoded roster | ❌ | ❌ | LEGAL_OPINION, ECONOMIC_ANALYSIS, SECURITY_BRIEF |
| **Activists** | 4-6 | Hardcoded roster | ❌ | ✅ | PROTEST, PETITION, PUBLIC_PRESSURE |

### 5.2 MK Persona Data (per agent)

From RZMAPPER + Knesset API:
- name_he, name_en, gender
- faction, coalition_member
- influence_score (0-100), loyalty_score (0-1)
- ideology_tags, stances (topic → position)
- personality (Hebrew text), rhetoric_style
- committee_roles, voting_history_summary
- twitter_handle
- Relationships (allies, rivals from RZMAPPER graph)
- Budget positions (from Open Budget API)

### 5.3 Tycoon/Industrialist Roster

| Name | Sector | Influence |
|------|--------|-----------|
| נוחי דנקנר | נדל"ן, תעשייה | Legacy influence |
| שרי אריסון | בנקאות, צדקה | Banking sector |
| מוטי בן משה | תקשורת, נדל"ן | Media pressure |
| אלפרד אקירוב | נדל"ן, תיירות | Construction lobby |
| צדיק בינו | אנרגיה | Energy sector |
| יצחק תשובה | אנרגיה, נדל"ן | Energy + real estate |
| אליעזר פישמן | בנקאות | Finance sector |
| ארנון מילצ'ן | תקשורת, הייטק | Media + connections |

---

## 6. User Input Options

### 6.1 Three Input Channels

**A. Free text** — question, bill proposal, what-if scenario
**B. Document upload** — enriches the simulation
**C. Configuration** — parameters, modifiers, layers

### 6.2 Uploadable Documents

| Document Type | Format | What the system does |
|---------------|--------|---------------------|
| Draft bill | PDF, DOCX, TXT | Extract clauses → identify affected factions → enriched simulation |
| Committee protocol | PDF (from knesset.gov.il) | Extract speakers + positions → update MK stances |
| Position paper / research | PDF, MD | Extract arguments → inject as "external knowledge" |
| News article / interview | URL or text | Extract quotes + positions → update personas |
| Budget data | CSV, XLSX, JSON | Numeric analysis → feed into budget debate |
| Coalition agreement | PDF | Extract commitments → check compliance |
| Court ruling / legal opinion | PDF | Extract legal position → feed to legal advisor agent |

### 6.3 Document Processing Pipeline

```
Document (PDF/DOCX/CSV/URL)
    → DOCUMENT ANALYZER (MiroFish GenerateOntologyTool)
        → Extract entities, arguments, clauses
    → ENRICHMENT
        → Cross-reference with 120 existing personas
        → Update relevant MK stances
        → Identify bill category
        → Generate bill_info
    → ENRICHED SIMULATION
        Agents "read" the document and react accordingly
```

---

## 7. Data Pipeline

### 7.1 Data Sources (14 automatic + user uploads)

| Source | Module | Interval | Data |
|--------|--------|----------|------|
| RZMAPPER entities | rzmapper_bridge.py | 6h | 1,282 entities, relationships, influence |
| Knesset OData: Members | knesset_member_collector.py | 24h | 120 MK profiles |
| Knesset OData: Bills | knesset_bill_collector.py | 12h | Bill texts, status |
| Knesset OData: Votes | knesset_vote_collector.py | 12h | Vote records |
| Knesset OData: Committees | knesset_committee_collector.py | 24h | Committee memberships |
| Knesset Protocols | protocol_collector.py | 12h | Plenum transcripts |
| Open Budget API | obudget_collector.py | 24h | Budget allocations |
| GuideStar IL | guidestar_collector.py | 7d | NGO data |
| Data.Gov IL | datagov_collector.py | 7d | Public datasets |
| Hebrew News RSS | live_data_feed.py | 5min | Ynet, Globes, Walla, Maariv |
| Telegram channels | rzmapper_bridge.py | 6h | 18 channels, 7,862+ messages |
| RZMAPPER Twitter | rzmapper_bridge.py | 6h | 22 seed accounts |
| BOOKDIGEST | bookdigest_collector.py | on-demand | Podcast insights |
| WikiData/Wikipedia | wikidata_collector.py | 7d | Entity enrichment |

### 7.2 Storage

| Component | Technology | Cost | Location |
|-----------|-----------|------|----------|
| Knowledge graph | KuzuDB (embedded) | $0 | `backend/data/kuzu_db/` |
| Agent memory | SQLite (WAL mode) | $0 | `backend/data/knesset/agent_memory.db` |
| Semantic search | Pinecone (free tier) | $0 | Cloud (100K vectors) |
| Local search | Qdrant (embedded) | $0 | `backend/data/qdrant/` |
| Collection state | SQLite | $0 | `backend/data/collection_state.db` |
| Feed cache | JSON files | $0 | `backend/data/knesset/feed_cache/` |

### 7.3 Data Flow Diagram

```
[14 Sources] → [Bridge & Normalization] → [KuzuDB + SQLite + Pinecone]
                                                    ↓
                                          [Simulation Engine]
                                          KnessetOrchestrator
                                             → KnessetLoop
                                             → Platform (8 modes)
                                             → Model Router (3 tiers)
                                                    ↓
                                          [Output]
                                          Vote tallies, coalition map,
                                          agent memories, AI analysis
```

---

## 8. LLM Model Routing

### 8.1 Three Tiers

| Tier | Criteria | Model | Cost/call |
|------|----------|-------|-----------|
| Primary | influence >= 85 OR committee chair | Claude CLI (Sonnet) | $0 (subscription) |
| Secondary | influence >= 60 OR faction leader | Groq llama-3.3-70b | ~$0.003 |
| Background | everyone else | Groq llama-3.1-8b | ~$0.0005 |

### 8.2 Platform-Specific Overrides

| Platform | Override |
|----------|---------|
| Negotiation | All agents minimum Secondary (negotiations need quality) |
| Brainstorm (divergent) | All agents Background (volume over quality) |
| Decision (devil's advocate role) | Force Primary |
| Twitter | Background for likes/RT, Secondary for original posts |

### 8.3 Cost Estimates

| Scenario | Cost |
|----------|------|
| Full plenum (120 MKs, 5 rounds) | ~$0.30 |
| Committee (12 MKs, 8 rounds) | ~$0.05 |
| Negotiation (4 sides, 10 rounds) | ~$0.03 |
| AI Advisor query | $0 (Claude CLI) |
| 10 simulations/day | ~$3/day |
| Heavy month | ~$50-80 |
| **Monthly hosting** | **€5.50 (Hetzner) + $0 (Cloudflare)** |

---

## 9. AI Parliamentary Advisor

### 9.1 Always-Visible Panel

Not a generic chatbot. A context-aware parliamentary advisor that:
- Knows what simulation is running
- Sees all agent actions in real-time
- Answers in Hebrew parliamentary language
- Can interview specific MKs on demand
- Suggests scenarios and follow-up simulations

### 9.2 Capabilities

| Command | What it does |
|---------|-------------|
| "למה הוא הצביע ככה?" | Explains MK reasoning from their persona + action log |
| "מה הסיכוי שהחוק יעבור?" | Analyzes current vote tally + swing MKs |
| "תביא לי את סמוטריץ'" | Opens interview chat with specific MK |
| "מה אם דרעי יוצא?" | Suggests running scenario with modifier |
| "תסכם את הדיון" | Generates structured Hebrew summary |
| "השווה לחוק הלאום 2018" | Historical query + comparison |

### 9.3 Technical Implementation

Uses existing `ClaudeChatPanel.vue` + `claude/chat` API endpoint.
Context injection: current simulation state + recent actions + bill info.
Model: Claude CLI (Sonnet) — $0 marginal cost.

---

## 10. Backend View ("Behind the Scenes" Tab)

### 10.1 Purpose

Exposes the MiroFish internals — pipeline status, knowledge graph, decision log, model routing, costs, agent memory — as a power-user tab.

### 10.2 Components

| Panel | Shows |
|-------|-------|
| Pipeline Status | 5-step progress bar (data → personas → simulation → analysis → report) |
| Knowledge Graph | D3.js force graph — MKs, factions, tycoons, relationships |
| Decision Log | Raw action log — every decision by every agent |
| Model Routing | Which tier each agent got, model used |
| Cost Tracker | Per-simulation and cumulative costs |
| Agent Memory | Episode count, strongest alliances, biggest rivalries |

---

## 11. Deployment Architecture

### 11.1 Stack

```
Browser → Cloudflare Edge (CDN + SSL) → cloudflared tunnel → Flask :5001 + Vue static
```

### 11.2 Infrastructure

| Component | Provider | Cost |
|-----------|----------|------|
| Compute | Hetzner CX22 (4GB RAM, 2 vCPU) | €5.50/mo |
| SSL + CDN + DDoS | Cloudflare (free tier) | $0 |
| Domain | predict.mudu.me (Cloudflare DNS) | $0 |
| Graph DB | KuzuDB embedded | $0 |
| Vector search | Pinecone free tier | $0 |
| LLM (primary) | Claude CLI subscription | $0 marginal |
| LLM (bulk) | Groq API | ~$5-15/mo |

### 11.3 Hetzner CX22 Constraints

- Use Groq-8B for ALL tiers (no local models)
- Reduce batch_size: 50 → 20
- SQLite only (no Neo4j)
- API-only mode available (no PixiJS if RAM tight)
- 120 MKs × 5 rounds ≈ 15 minutes

### 11.4 Replaces Traefik

MiroFish original uses Traefik for reverse proxy + SSL. KnessetSim uses Cloudflare Tunnel instead:
- No open ports required
- Automatic SSL certificates
- CDN + DDoS protection included
- Single command: `cloudflared tunnel run`

---

## 12. File Structure

### 12.1 Backend (existing + new)

```
MIROFISH/backend/app/services/knesset/
├── orchestrator.py             # 🔧 Modified — bridge, memory, platform param
├── knesset_loop.py             # 🔧 Modified — platform delegation
├── parliament_state.py         # Existing — bills, votes, coalitions
├── persona_generator.py        # 🔧 Modified — auxiliary agents
├── types.py                    # 🔧 Modified — AuxiliaryPersona, new actions
├── types_extended.py           # Existing
├── rzmapper_bridge.py          # ✅ New — RZMAPPER data bridge
├── memory_store.py             # ✅ New — SQLite persistent memory
├── multi_model_router.py       # 🔧 Modified — 3 tiers, platform-aware
├── coalition_detector.py       # Existing
├── voting_patterns.py          # Existing
├── scenarios.py                # Existing
├── chat_interface.py           # Existing
├── historical_query.py         # Existing
├── live_data_feed.py           # 🔧 Modified — RZMAPPER social
├── data_daemon.py              # 🔧 Modified — rzmapper:sync
├── hebrew_nlp.py               # Existing
├── ontology.py                 # 🔧 Modified — rzmapper source
├── platforms/                  # ✅ New directory
│   ├── __init__.py
│   ├── base_platform.py        # ABC for all platforms
│   ├── plenum.py               # Extracted from knesset_loop.py
│   ├── roundtable.py           # Committee discussions
│   ├── negotiation.py          # Coalition negotiations
│   ├── brainstorm.py           # Idea generation
│   └── decision.py             # Structured decision-making
└── collectors/
    ├── (14 existing collectors)
    └── bookdigest_collector.py  # ✅ New
```

### 12.2 Frontend (existing + needs upgrade)

```
MIROFISH/frontend/src/components/knesset/
├── HemicycleChart.vue          # 🔨 Needs upgrade — interactive, clickable seats
├── VoteTally.vue               # Existing
├── MKCard.vue                  # Existing
├── BillCard.vue                # Existing
├── ChatPanel.vue               # Existing
├── PlenumFeed.vue              # Existing
├── FactionBar.vue              # Existing
├── ClaudeChatPanel.vue         # Existing — becomes "Parliamentary Advisor"
├── AnalysisChatPanel.vue       # Existing
├── CoalitionGraph.vue          # ✅ New — Cytoscape.js
├── RoundtableView.vue          # ✅ New
├── NegotiationView.vue         # ✅ New
├── BrainstormView.vue          # ✅ New
└── DecisionView.vue            # ✅ New
```

### 12.3 API Endpoints

**Simulation**: POST simulate, GET status, POST inject, GET platforms, POST scenario
**MKs**: GET mks, GET mks/:id, POST chat, GET factions
**Data**: GET bills, GET stats, POST query
**AI Advisor**: POST claude/chat

---

## 13. What's Kept from MiroFish vs Changed vs Removed

### Kept (Core Infrastructure)
- Flask backend + blueprint routing
- KuzuDB graph storage abstraction
- LLMRouter multi-provider system
- OASIS agent framework (for Twitter mode)
- Report agent + ReACT pattern
- Task management system
- Docker deployment structure
- Document parsing (PDF, Markdown, text)
- D3.js graph visualization (in Backend tab)

### Changed Significantly
- Frontend: wizard → Command Center with Knesset UI
- Simulation: OASIS subprocess → KnessetLoop direct (+ OASIS for Twitter)
- Personas: LLM-generated → real data from 14 sources
- All prompts: Chinese → Hebrew
- All platforms: new (5 custom + press conference + Twitter + custom)
- Memory: none → SQLite persistent with relationship tracking
- Data: user upload required → automatic collection
- Model routing: single model → 3 tiers with platform overrides
- Deployment: Traefik → Cloudflare Tunnel

### Removed
- Chinese language support
- Alibaba Qwen integration
- Generic social media as primary mode (kept as Twitter mode)
- Mandatory document upload before simulation

---

## 14. Implementation Status

### Already Built (this session)

| Component | Lines | Status |
|-----------|-------|--------|
| rzmapper_bridge.py | 592 | ✅ Complete |
| memory_store.py | 376 | ✅ Complete |
| platforms/base_platform.py | 156 | ✅ Complete |
| platforms/plenum.py | 162 | ✅ Complete |
| platforms/roundtable.py | 332 | ✅ Complete |
| platforms/negotiation.py | 290 | ✅ Complete |
| platforms/brainstorm.py | 248 | ✅ Complete |
| platforms/decision.py | 351 | ✅ Complete |
| bookdigest_collector.py | 142 | ✅ Complete |
| 5 Vue components | ~25KB | ✅ Complete |
| orchestrator.py mods | — | ✅ Complete |
| knesset_loop.py refactor | — | ✅ Complete |
| multi_model_router.py upgrade | — | ✅ Complete |
| data_daemon.py + ontology.py | — | ✅ Complete |
| live_data_feed.py + API updates | — | ✅ Complete |
| types.py (AuxiliaryPersona) | — | ✅ Complete |
| persona_generator.py (auxiliaries) | — | ✅ Complete |

### Still Needed

| Component | Priority | Effort |
|-----------|----------|--------|
| Press Conference platform | HIGH | 1 day |
| Social Layer (Twitter overlay) | HIGH | 2 days |
| Frontend Command Center redesign | HIGH | 3-5 days |
| Interactive Hemicycle upgrade | HIGH | 2 days |
| Tycoon/Industrialist agent roster | MEDIUM | 1 day |
| Activist agent roster | MEDIUM | 0.5 day |
| Document upload + analysis pipeline | MEDIUM | 2 days |
| WebSocket for real-time updates | MEDIUM | 1 day |
| Backend tab (graph + pipeline + costs) | MEDIUM | 2 days |
| Quick Scenarios presets | LOW | 1 day |
| Modifiers system | LOW | 1 day |
| Hetzner deployment | LOW | 0.5 day |
