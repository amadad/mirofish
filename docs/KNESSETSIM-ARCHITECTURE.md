# KnessetSim — Complete Architecture Document

## הכנסת הווירטואלית | The Virtual Knesset

> A gamified Israeli parliament simulator powered by real data, multi-agent LLM simulation,
> and a 2D virtual world where 120 AI MKs debate, vote, and form coalitions.

---

## 1. HIGH-LEVEL FLOW

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERACTION                          │
│  "מה יקרה אם אציע חוק לגיוס חובה לחרדים?"                  │
│  "What if I propose mandatory Haredi military service?"     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              ORCHESTRATOR (orchestrator.py)                  │
│  1. Parse user query → extract bill topic & constraints     │
│  2. Historical lookup → "Has this been tried?"              │
│  3. Build simulation config (which MKs, how many rounds)    │
│  4. Launch KnessetLoop                                      │
│  5. Generate report                                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│  HISTORICAL  │ │ KNESSET  │ │   REPORT     │
│  QUERY       │ │  LOOP    │ │  GENERATOR   │
│  (Phase 3)   │ │ (Phase 2)│ │  (Phase 4)   │
│              │ │          │ │              │
│ HybridSearch │ │ 120 MKs  │ │ Claude Opus  │
│ over 500+    │ │ x N rds  │ │ analysis     │
│ real bills   │ │ via Groq │ │              │
└──────────────┘ └────┬─────┘ └──────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              2D VIRTUAL KNESSET WORLD (Phase 5)             │
│  PixiJS + pixi-react + Tiled map                           │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │            PLENUM HALL (hemicycle)                │       │
│  │    ●●●  ●●●  ●●●  ●●●  ●●●  ←── Opposition    │       │
│  │   ●●●● ●●●● ●●●● ●●●● ●●●●                    │       │
│  │  ●●●●● ●●●●● ●●●●● ●●●●● ●●●●● ←── Coalition │       │
│  │         [SPEAKER PODIUM]                         │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │Committee │  │Committee │  │ Cafeteria│ ←── casual       │
│  │Room A    │  │Room B    │  │          │     negotiations │
│  └──────────┘  └──────────┘  └──────────┘                 │
│                                                             │
│  ┌──────────┐  ┌──────────┐                                │
│  │Media Room│  │Corridors │ ←── lobby + deal-making        │
│  └──────────┘  └──────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. DIRECTORY STRUCTURE

```
MIROFISH/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── knesset.py              # NEW: 8 REST endpoints
│   │   │   ├── simulation.py           # Existing social-media sim
│   │   │   └── ...
│   │   ├── services/
│   │   │   ├── knesset/                # NEW: All Knesset-specific code
│   │   │   │   ├── __init__.py
│   │   │   │   ├── types.py            # KnessetPersona, KnessetAction, BillState
│   │   │   │   ├── parliament_state.py # Bills lifecycle, coalition map, voting
│   │   │   │   ├── knesset_loop.py     # Fork of FastAgentLoop for parliament
│   │   │   │   ├── persona_generator.py# Real MK data → LLM personas
│   │   │   │   ├── historical_query.py # "Has this been tried?" search
│   │   │   │   ├── voting_patterns.py  # Pure Python: alignment, cohesion
│   │   │   │   ├── orchestrator.py     # Main entry: query → sim → report
│   │   │   │   ├── scenarios.py        # "What if?" scenario engine
│   │   │   │   └── chat_interface.py   # Talk to MKs individually/groups
│   │   │   ├── fast_agent_loop.py      # Existing (untouched)
│   │   │   ├── agent_memory.py         # Existing (reused as-is)
│   │   │   ├── data_injector.py        # Existing (reused as-is)
│   │   │   ├── hybrid_search.py        # Existing (reused as-is)
│   │   │   └── ...
│   │   └── ...
│   ├── config/
│   │   └── llm_router.yaml            # MODIFIED: add knesset_* routes
│   ├── scripts/
│   │   ├── knesset_vote_collector.py   # NEW: Fetch votes from OData API
│   │   ├── knesset_twitter_collector.py# NEW: Fetch MK tweets
│   │   ├── import_knesset_data.py      # NEW: RZMAPPER → KuzuDB
│   │   └── index_knesset_history.py    # NEW: Bills → HybridSearch
│   └── data/
│       └── knesset/                    # NEW: Raw Knesset data cache
│           ├── votes_raw.json
│           ├── twitter/                # Per-MK tweet archives
│           └── personas/              # Generated persona JSONs
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── knesset/               # NEW: Knesset views
│   │   │   │   ├── KnessetHome.vue
│   │   │   │   ├── KnessetSimulate.vue
│   │   │   │   ├── KnessetResults.vue
│   │   │   │   ├── KnessetMKDetail.vue
│   │   │   │   └── KnessetHistory.vue
│   │   │   └── ... (existing views)
│   │   ├── components/
│   │   │   ├── knesset/               # NEW: Knesset components
│   │   │   │   ├── VirtualWorld.vue   # PixiJS 2D world renderer
│   │   │   │   ├── HemicycleChart.vue # SVG seating chart
│   │   │   │   ├── VoteTally.vue      # Animated vote counter
│   │   │   │   ├── MKCard.vue         # MK profile card
│   │   │   │   ├── BillCard.vue       # Bill summary card
│   │   │   │   ├── ChatPanel.vue      # Side chat with MKs
│   │   │   │   ├── FactionBar.vue     # Coalition/opposition bar
│   │   │   │   ├── PlenumFeed.vue     # Live speech/action feed
│   │   │   │   └── TimelineRound.vue  # Round-by-round timeline
│   │   │   └── ... (existing components)
│   │   ├── assets/
│   │   │   └── knesset/               # NEW: Knesset assets
│   │   │       ├── tilemap/           # Tiled map JSON + tilesets
│   │   │       ├── sprites/           # MK character sprites
│   │   │       └── ui/               # Icons, faction logos
│   │   └── api/
│   │       └── knesset.js             # NEW: Knesset API client
│   └── ...
└── docs/
    └── KNESSETSIM-ARCHITECTURE.md     # This file
```

---

## 3. DATA PIPELINE

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                                 │
├─────────────┬─────────────┬──────────────┬──────────────────────┤
│ Knesset     │ RZMAPPER    │ Twitter/X    │ News RSS             │
│ OData API   │ Entities    │ MK Accounts  │ Feeds                │
│             │             │              │                      │
│ • Members   │ • 159 MK    │ • Tweets     │ • Ynet               │
│ • Factions  │   profiles  │ • Followers  │ • Haaretz             │
│ • Bills     │ • Positions │ • Retweets   │ • Knesset Channel    │
│ • Votes     │ • Timeline  │ • Sentiment  │ • Globes             │
│ • Positions │ • Influence │              │                      │
│ • Committees│   scores    │              │                      │
└──────┬──────┴──────┬──────┴──────┬───────┴──────────┬───────────┘
       │             │             │                  │
       ▼             ▼             ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│              IMPORT & NORMALIZATION LAYER                         │
│                                                                  │
│  scripts/import_knesset_data.py                                  │
│  ├── Merge knesset_*.json + person_knesset_*.json (dedupe)       │
│  ├── Resolve encoding issues (UTF-8 normalization)               │
│  ├── Match PersonID across data sources                          │
│  ├── Build cross-reference indexes                               │
│  └── Write to KuzuDB graph                                      │
│                                                                  │
│  scripts/knesset_vote_collector.py                               │
│  ├── Fetch KNS_VoteStatistic (per-MK per-vote records)           │
│  ├── Fetch KNS_BillInitiator (bill sponsors)                     │
│  ├── Link votes ↔ bills ↔ MKs                                   │
│  └── Cache to data/knesset/votes_raw.json                        │
│                                                                  │
│  scripts/knesset_twitter_collector.py                            │
│  ├── Find MK Twitter handles (from Knesset website / manual)     │
│  ├── Fetch recent tweets (last 2 years)                          │
│  ├── Extract stance signals from tweet content                   │
│  └── Cache to data/knesset/twitter/                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE GRAPH (KuzuDB)                       │
│                                                                  │
│  NODES:                                                          │
│  ┌────────────┐  ┌────────────┐  ┌──────────┐  ┌────────────┐  │
│  │    MK      │  │  Faction   │  │   Bill   │  │ Committee  │  │
│  │ person_id  │  │ faction_id │  │ bill_id  │  │ comm_id    │  │
│  │ name_he    │  │ name_he    │  │ name_he  │  │ name_he    │  │
│  │ gender     │  │ knesset_n  │  │ status   │  │ knesset_n  │  │
│  │ influence  │  │ is_current │  │ sub_type │  │            │  │
│  │ ideology[] │  │ coalition? │  │ sponsor  │  │            │  │
│  └─────┬──────┘  └─────┬──────┘  └────┬─────┘  └─────┬──────┘  │
│        │               │              │               │          │
│  EDGES:│               │              │               │          │
│  ──────┼───────────────┼──────────────┼───────────────┼────      │
│  MEMBER_OF ────────────┘              │               │          │
│  VOTED_ON (yes/no/abstain) ───────────┘               │          │
│  SPONSORED ───────────────────────────┘               │          │
│  SAT_ON / CHAIRED ────────────────────────────────────┘          │
│  ALLIED_WITH (MK ↔ MK, weight = voting alignment)               │
│  OPPOSES (MK ↔ MK, from voting divergence)                      │
│  FACTION_COALITION (Faction → Coalition/Opposition)              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              PERSONA GENERATION (one-time + refresh)              │
│                                                                  │
│  persona_generator.py                                            │
│  For each MK:                                                    │
│    Input: name, faction, positions, voting history, tweets,      │
│           committee roles, bill sponsorships, news mentions      │
│    LLM (Groq llama-3.3-70b):                                    │
│      → ideology_tags: ["ביטחוני", "כלכלי-חופשי", "דתי-מסורתי"]  │
│      → personality: "מו"מ תקיף, נאומים רגשיים, נאמן לסיעה"      │
│      → stances: {                                                │
│          "גיוס_חרדים": "בעד_בתנאים",                            │
│          "הרפורמה_המשפטית": "נגד_חזק",                          │
│          "שני_מדינות": "נגד",                                    │
│          "תקציב_חינוך": "בעד"                                    │
│        }                                                         │
│      → rhetoric_style: "populist" | "technocrat" | "ideologue"  │
│      → loyalty_score: 0.0-1.0 (how often votes with faction)    │
│    Output: KnessetPersona → data/knesset/personas/{mk_id}.json  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                    SIMULATION ENGINE
```

---

## 4. SIMULATION ENGINE (KnessetLoop)

```
┌─────────────────────────────────────────────────────────────────┐
│                    KNESSSET LOOP                                 │
│              (Fork of FastAgentLoop)                              │
│                                                                  │
│  INITIALIZATION:                                                 │
│  ├── Load 120 KnessetPersona objects from graph + persona cache  │
│  ├── Initialize ParliamentState:                                 │
│  │   ├── coalition_map: {faction → coalition/opposition}         │
│  │   ├── bills: {} (empty, user's bill injected at round 1)     │
│  │   ├── voting_records: []                                      │
│  │   └── session_agenda: []                                      │
│  ├── Connect DataInjector (news RSS feeds)                       │
│  └── Connect AgentMemoryStore (load cross-sim memories)          │
│                                                                  │
│  ROUND LOOP (5-10 rounds per simulation):                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Round N                                                  │   │
│  │                                                           │   │
│  │  1. INJECT EVENTS                                         │   │
│  │     ├── DataInjector.get_events_for_round(N)              │   │
│  │     ├── News: "בג"ץ פסל חוק X" (Supreme Court struck X)   │   │
│  │     └── Scheduled: "הצעת חוק Y עלתה להצבעה" (Bill Y vote)│   │
│  │                                                           │   │
│  │  2. AGENT DECISIONS (parallel batches of 50)              │   │
│  │     For each MK:                                          │   │
│  │     ┌────────────────────────────────────────────────┐    │   │
│  │     │ PROMPT (Hebrew):                                │    │   │
│  │     │ אתה {name}, חבר כנסת מסיעת {faction}.           │    │   │
│  │     │ רקע: {background}                               │    │   │
│  │     │ עמדות: {stances}                                │    │   │
│  │     │ זיכרון: {memory from past simulations}          │    │   │
│  │     │                                                 │    │   │
│  │     │ מצב הכנסת:                                      │    │   │
│  │     │ - הצעות חוק פתוחות: {bills}                     │    │   │
│  │     │ - קואליציה: {coalition_status}                   │    │   │
│  │     │ - אירועים אחרונים: {injected_events}            │    │   │
│  │     │                                                 │    │   │
│  │     │ בחר פעולה:                                      │    │   │
│  │     │ PROPOSE_BILL | VOTE | SPEAK_IN_PLENUM |         │    │   │
│  │     │ FORM_ALLIANCE | DEFECT | LOBBY | DO_NOTHING     │    │   │
│  │     │                                                 │    │   │
│  │     │ JSON: {"action":"VOTE", "bill_id":"...",        │    │   │
│  │     │   "vote":"בעד", "reasoning":"..."}              │    │   │
│  │     └────────────────────────────────────────────────┘    │   │
│  │                                                           │   │
│  │     → LLMRouter.chat(task="knesset_decision") → Groq     │   │
│  │     → Parse response → KnessetAction                      │   │
│  │     → Apply to ParliamentState                            │   │
│  │                                                           │   │
│  │  3. PARLIAMENT SECRETARY (deterministic, no LLM)          │   │
│  │     ├── Count votes on each bill in voting state           │   │
│  │     ├── Advance bills through readings:                    │   │
│  │     │   proposed → committee → 1st_reading →              │   │
│  │     │   2nd_reading → 3rd_reading → passed/failed         │   │
│  │     ├── Record coalition discipline violations             │   │
│  │     └── Log attendance (who acted vs. DO_NOTHING)         │   │
│  │                                                           │   │
│  │  4. UPDATE MEMORIES                                       │   │
│  │     ├── AgentMemoryStore.save_round(actions)              │   │
│  │     └── Update MK relationships based on alliances/votes  │   │
│  │                                                           │   │
│  │  5. EMIT TO FRONTEND                                      │   │
│  │     ├── Round summary → WebSocket/SSE                     │   │
│  │     ├── Agent positions in 2D world → update sprites      │   │
│  │     └── Chat feed → PlenumFeed component                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  POST-SIMULATION:                                                │
│  ├── AgentMemoryStore.save_simulation_results()                  │
│  ├── ReportGenerator.generate() (Claude Opus)                    │
│  └── Persist all actions to actions.jsonl                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. PARLIAMENTARY ACTIONS

| Action | Parameters | Effect |
|--------|-----------|--------|
| `PROPOSE_BILL` | `{title_he, summary, category}` | Creates new BillState, sponsor = this MK |
| `VOTE` | `{bill_id, vote: "בעד"/"נגד"/"נמנע"}` | Records vote, updates tally |
| `SPEAK_IN_PLENUM` | `{topic, speech_he, stance}` | Adds to plenum feed, may influence others |
| `LOBBY` | `{target_mk_id, bill_id, argument}` | Private persuasion, affects target's next decision |
| `FORM_ALLIANCE` | `{target_faction, terms}` | Cross-faction deal proposal |
| `DEFECT` | `{from_faction, reason}` | Leave faction (dramatic, rare) |
| `AMEND_BILL` | `{bill_id, amendment_text}` | Modify bill before next reading |
| `DO_NOTHING` | `{}` | Stay silent this round |

---

## 6. BILL LIFECYCLE

```
                    ┌─────────┐
                    │PROPOSED │ ←── MK submits via PROPOSE_BILL
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │COMMITTEE│ ←── Assigned committee discusses
                    └────┬────┘
                         │
                    ┌────▼────────┐
                    │1ST READING  │ ←── Preliminary vote (simple majority)
                    └────┬────────┘
                    PASS │ FAIL → FAILED
                    ┌────▼────────┐
                    │2ND READING  │ ←── Detailed debate, amendments allowed
                    └────┬────────┘
                    PASS │ FAIL → FAILED
                    ┌────▼────────┐
                    │3RD READING  │ ←── Final vote (61 of 120 needed)
                    └────┬────────┘
                    PASS │ FAIL → FAILED
                    ┌────▼────┐
                    │ PASSED  │ ←── Becomes law!
                    └─────────┘
```

---

## 7. AGENT MEMORY ARCHITECTURE

```
┌─────────────────────────────────────────────────────┐
│              MK MEMORY (per agent, persistent)       │
│                                                      │
│  STREAM (chronological):                             │
│  ├── [sim_1, round_3] Voted FOR judicial reform      │
│  ├── [sim_1, round_5] Allied with Likud on budget    │
│  ├── [sim_2, round_1] Spoke against Haredi draft     │
│  └── [sim_2, round_4] Defected from coalition vote   │
│                                                      │
│  BELIEFS (synthesized, decaying):                    │
│  ├── "הקואליציה יציבה" (confidence: 0.7)             │
│  ├── "חוק הגיוס לא יעבור" (confidence: 0.8)          │
│  └── "יש לי 4 בעלי ברית בוועדה" (confidence: 0.9)   │
│                                                      │
│  RELATIONSHIPS (other MKs):                          │
│  ├── MK_42: ally (strength: 0.8, from 3 sims)       │
│  ├── MK_17: rival (strength: 0.6, from 2 sims)      │
│  └── MK_89: neutral (no significant interaction)     │
│                                                      │
│  VOTING PATTERNS:                                    │
│  ├── Coalition alignment: 78%                        │
│  ├── Security bills: 92% FOR                         │
│  ├── Economic bills: 65% FOR                         │
│  └── Religious bills: 45% AGAINST                    │
│                                                      │
│  RETRIEVAL (for new prompts):                        │
│  ├── Recency: recent memories weighted 1.5x          │
│  ├── Importance: defection/alliance weighted 2x      │
│  └── Relevance: BGE-M3 similarity to current topic   │
└─────────────────────────────────────────────────────┘
```

---

## 8. USER INTERACTION MODES

### Mode 1: "What if?" Simulation
```
User: "מה יקרה אם נציע חוק גיוס לכל החרדים מגיל 18?"
→ Orchestrator parses → Finds historical precedents → Runs 5-round sim
→ Report: 47 בעד, 62 נגד, 11 נמנעים — נפל בקריאה ראשונה
→ Key opponents: ש"ס (12 נגד), יהדות התורה (7 נגד)
→ "What would it take?": Need 14 more votes → possible with Yesh Atid swing
```

### Mode 2: Chat with MKs
```
User: "תדבר עם סמוטריץ' על התקציב"
→ Loads Smotrich persona + memory + recent simulation context
→ Interactive chat in Hebrew (MK responds in character)
→ Can probe: "למה הצבעת נגד?" / "מה התנאי שלך?"
```

### Mode 3: Group Discussion
```
User: "תפתח דיון בוועדת הכלכלה על ביטוח בריאות"
→ Loads 9 committee members
→ Multi-agent discussion (each responds in turn)
→ User can interject, redirect, or observe
```

### Mode 4: Historical Analysis
```
User: "מה קרה כשניסו להעביר חוק הלאום?"
→ HybridSearch finds real bills + voting records
→ Shows: who voted, who spoke, what happened
→ Compare to current Knesset: "Today it would pass 64-56"
```

### Mode 5: Scenario Explorer
```
User: "מה אם לפיד מנצח בבחירות?"
→ Scenario engine reconfigures coalition map
→ Runs simulation with new coalition
→ Shows: which laws would pass/fail, policy changes
```

---

## 9. 2D VIRTUAL WORLD

Built with **PixiJS + pixi-react** (adapted from AI Town architecture):

### Map Layout (Tiled editor)
```
┌────────────────────────────────────────────────┐
│                KNESSET BUILDING                 │
│                                                 │
│  ┌──────────────────────────────────────┐      │
│  │          PLENUM HALL                  │      │
│  │     (hemicycle seating, 120 seats)    │      │
│  │     Speaker podium at center-front    │      │
│  │     Gallery above for observers       │      │
│  └──────────────────────────────────────┘      │
│                                                 │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          │
│  │כלכלה │ │ חוקה │ │ ביטחון│ │חינוך │ ← Committees
│  │Econ  │ │Const.│ │Defense│ │Educ. │          │
│  └──────┘ └──────┘ └──────┘ └──────┘          │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Cafeteria│  │ Corridors│  │Media Room│     │
│  │ (deals)  │  │ (lobby)  │  │(speeches)│     │
│  └──────────┘  └──────────┘  └──────────┘     │
│                                                 │
│  ┌──────────┐  ┌──────────┐                    │
│  │PM Office │  │Opposition│                    │
│  │          │  │  Office  │                    │
│  └──────────┘  └──────────┘                    │
└────────────────────────────────────────────────┘
```

### Agent Behavior in 2D World
- MKs move between rooms based on their actions
- VOTE → walk to plenum, sit in faction section
- SPEAK_IN_PLENUM → walk to podium
- LOBBY → walk to target MK's location
- DO_NOTHING → stay in cafeteria/corridor
- Speech bubbles show abbreviated action text
- Faction colors on each MK sprite

### Tech Stack
- **PixiJS** (v7+) via `pixi-react` — 2D rendering
- **Tiled** map editor → JSON export → converted to game format
- **Sprite sheets** — pixel art MK characters (auto-generated or hand-drawn)
- **Smooth animation** — interpolated position updates between rounds

---

## 10. LLM ROUTING

```yaml
# Added to config/llm_router.yaml

routing:
  knesset_decision:        # 120 MKs × N rounds — MUST be fast + cheap
    primary: { provider: groq, model: "llama-3.3-70b-versatile" }
    fallback:
      - { provider: openai, model: "gpt-4o-mini" }
    temperature: 0.7
    max_tokens: 512

  knesset_persona:         # One-time persona generation per MK
    primary: { provider: groq, model: "llama-3.3-70b-versatile" }
    fallback:
      - { provider: openai, model: "gpt-4o-mini" }
    temperature: 0.8
    max_tokens: 1024

  knesset_analysis:        # Historical analysis, reports
    primary: { provider: anthropic_sonnet, model: "claude-sonnet-4-5-20250929" }
    fallback:
      - { provider: openai, model: "gpt-4o" }
    temperature: 0.3
    max_tokens: 4096

  knesset_chat:            # Interactive chat with MK persona
    primary: { provider: groq, model: "llama-3.3-70b-versatile" }
    fallback:
      - { provider: anthropic_sonnet, model: "claude-sonnet-4-5-20250929" }
    temperature: 0.8
    max_tokens: 1024
```

---

## 11. COST MODEL

| Operation | Provider | Tokens | Cost |
|-----------|----------|--------|------|
| Full simulation (120 MKs × 5 rounds) | Groq | ~450K | ~$0.65 |
| Persona generation (120 MKs × 1) | Groq | ~120K | ~$0.17 |
| Historical query | Claude Sonnet | ~8K | ~$0.15 |
| Deep analysis report | Claude Opus | ~10K | ~$0.50 |
| MK chat (10 turns) | Groq | ~15K | ~$0.02 |
| **Typical session** | Mixed | ~600K | **~$1.50** |

---

## 12. API ENDPOINTS

```
POST /api/knesset/simulate         # Run new simulation
  Body: { question_he, scenario?, rounds?, mks_filter? }
  Returns: { simulation_id, status: "running" }

GET  /api/knesset/simulate/<id>    # Get simulation status + results
  Returns: { status, current_round, actions[], report? }

POST /api/knesset/query            # Historical query
  Body: { question_he }
  Returns: { similar_bills[], analysis_he, probability }

GET  /api/knesset/mks              # List all MKs with brief info
  Returns: [{ id, name_he, faction, influence, is_current }]

GET  /api/knesset/mks/<id>         # Full MK detail + history
  Returns: { persona, voting_patterns, memory, relationships }

POST /api/knesset/chat             # Chat with MK or group
  Body: { mk_ids[], message_he, context? }
  Returns: { responses: [{ mk_id, response_he }] }

GET  /api/knesset/factions         # Faction list + coalition status
  Returns: [{ id, name_he, seats, coalition?, members[] }]

POST /api/knesset/scenario         # Run what-if scenario
  Body: { type: "election_change"|"defection"|"crisis", params }
  Returns: { simulation_id }

GET  /api/knesset/bills            # Historical bills
  Params: ?search=&faction=&status=
  Returns: [{ id, name_he, status, votes_for, votes_against }]

GET  /api/knesset/stats            # Dashboard stats
  Returns: { mks_count, bills_count, simulations_run, avg_accuracy }
```

---

## 13. HISTORICAL MKs (FUTURE EXPANSION)

The system is designed to scale to historical Knessets (1-24):
- Import all 1001 MK profiles from RZMAPPER
- Generate personas for historical MKs based on their era's context
- "What would Ben-Gurion think about judicial reform?"
- Cross-era simulations: mix current and historical MKs
- Timeline view: how the Knesset evolved over 75 years

---

## 14. LEVERAGE & INFLUENCE AXES

The simulation tracks and visualizes:

| Axis | What it Measures | How it's Calculated |
|------|-----------------|---------------------|
| **Coalition Loyalty** | How often MK votes with coalition | voting_records / total_votes |
| **Cross-Faction Influence** | Who listens to this MK from other factions | successful LOBBY actions |
| **Media Power** | MK's public narrative weight | Twitter followers + media mentions |
| **Committee Power** | Control over legislative process | committee chair positions |
| **Deal-Making** | Ability to form alliances | successful FORM_ALLIANCE + trades |
| **Ideological Consistency** | Does MK vote their beliefs or party line? | stances vs actual votes |

These become interactive filters in the frontend — "Show me the most influential cross-faction dealmakers."
