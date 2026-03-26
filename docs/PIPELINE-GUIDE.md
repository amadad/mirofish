# MIROFISH Pipeline Guide

## Quick Reference

```
Documents ──► Ontology ──► Graph ──► Simulation ──► Report ──► Interview
  PyMuPDF      Claude       Claude     CAMEL-OASIS    ReACT      OASIS
  $0           $0.01        $0.05      $3-50          $0.50      $0.01/ea
```

---

## Stage 1: Document Upload

| Field | Value |
|-------|-------|
| **Component** | Flask multipart upload + PyMuPDF + charset-normalizer |
| **API** | `POST /api/graph/ontology/generate` (multipart form) |
| **Input** | PDF, TXT, DOCX, HTML files |
| **Processing** | PyMuPDF extracts text, charset-normalizer handles encoding |
| **Chunking** | 500 chars per chunk, 50 char overlap |
| **LLM Calls** | 0 |
| **Cost** | $0 |
| **Files** | `app/__init__.py` (upload handler), `app/services/ontology_generator.py` |

---

## Stage 2: Ontology Generation

| Field | Value |
|-------|-------|
| **Component** | `OntologyGenerator` |
| **API** | Same as Stage 1 (combined endpoint) |
| **Input** | Extracted text + `simulation_requirement` |
| **Output** | JSON schema: `entity_types[]` + `edge_types[]` with attributes |
| **LLM** | Claude CLI (Sonnet) — 1 call |
| **Prompt** | Analyze text, generate entity/relationship ontology for social simulation |
| **Cost** | ~$0.01 |
| **Files** | `app/services/ontology_generator.py` |

**Output Example:**
```json
{
  "entity_types": [
    {"name": "KnessetMember", "attributes": ["full_name", "party", "role"]}
  ],
  "edge_types": [
    {"name": "MEMBER_OF", "source": "KnessetMember", "target": "PoliticalParty"}
  ]
}
```

---

## Stage 3: Graph Build

| Field | Value |
|-------|-------|
| **Component** | `EntityExtractor` + `GraphStorage` + `HybridSearchService` |
| **API** | `POST /api/graph/build` → async task |
| **Input** | `project_id` (from Stage 2) |
| **Output** | Knowledge graph: nodes (entities) + edges (relationships) |
| **Storage** | JSON files or KuzuDB (embedded graph DB) |
| **Embedding** | BGE-M3 (BAAI/bge-m3) — 1024-dim vectors, multilingual |
| **Search** | Qdrant embedded — vector + BM25 hybrid |
| **Reranker** | BGE-reranker-v2-m3 (cross-encoder) |
| **Algorithm** | RRF (Reciprocal Rank Fusion) — semantic + keyword |
| **LLM** | Claude CLI — 1-3 calls per document chunk |
| **Cost** | ~$0.05 per document |
| **Files** | `app/services/graph_storage.py`, `app/services/hybrid_search.py`, `app/services/entity_reader.py` |

**Monitor:** `GET /api/graph/task/{task_id}` → `{status, progress}`

---

## Stage 4: Simulation

| Field | Value |
|-------|-------|
| **Component** | CAMEL-OASIS social simulation engine |
| **API** | `POST /api/simulation/create` → `POST /api/simulation/start` |
| **Input** | `graph_id`, platform (Twitter/Reddit), rounds |
| **Agent Framework** | OASIS `SocialAgent` + `AgentGraph` |
| **Platforms** | Twitter simulator, Reddit simulator (built-in OASIS) |
| **Agent Graph** | Neo4j driver (relationships) + igraph (algorithms) |
| **Profile Gen** | `OasisProfileGenerator` — Claude generates persona per entity |
| **Agent Actions** | `LLMAction` (LLM decides: post/like/reply/vote) |
| **Interview** | `ManualAction` + `ActionType.INTERVIEW` |
| **IPC** | JSON file-based (backend ↔ simulation subprocess) |
| **Platform DB** | SQLite (OASIS internal — posts, likes, follows) |
| **LLM per round** | 1 call × number of agents |
| **Cost** | **Most expensive** — 120 agents × 10 rounds = 1,200 calls |
| **Files** | `app/services/simulation_runner.py`, `scripts/run_twitter_simulation.py`, `scripts/run_reddit_simulation.py` |

### Optimization: Multi-Model Tiering

| Tier | Agents | Model | Tokens | Purpose |
|------|--------|-------|--------|---------|
| Primary | 10 leaders | Claude Opus | 512 | Deep reasoning |
| Secondary | 30 key MKs | Claude Sonnet | 384 | Good analysis |
| Background | 80 minor MKs | Groq Llama 70B | 256 | Fast + free |
| Rule-based | 380 entities | No LLM | 0 | Deterministic |

**File:** `app/services/knesset/multi_model_router.py`

### Profile Caching
Pre-generate profiles once, reuse across simulations:
- **Warm:** `POST /api/knesset/profiles/warm` → generates all profiles
- **Invalidate:** `POST /api/knesset/profiles/invalidate`
- **Cache dir:** `data/profiles_cache/`
- **File:** `app/services/oasis_profile_generator.py`

### Live Data Feed
Real-time Knesset events injected into agent context:
- **Inject:** `POST /api/knesset/live-feed/inject`
- **Events:** `GET /api/knesset/live-feed/events`
- **Sources:** Knesset API, Israeli news RSS, manual
- **File:** `app/services/knesset/live_data_feed.py`

### Batch Parallel
Run 10 agents simultaneously instead of 1-by-1:
- **File:** `app/services/knesset/batch_runner.py`
- Uses asyncio semaphore + token-bucket rate limiter

---

## Stage 5: Report

| Field | Value |
|-------|-------|
| **Component** | `ReportAgent` (ReACT autonomous agent) |
| **API** | `POST /api/report/generate` → async task |
| **Input** | `simulation_id` |
| **Pattern** | ReACT loop: Think → Act (search graph) → Observe → Think → Write |
| **Tools** | InsightForge (graph search), PanoramaSearch (hybrid), QuickSearch |
| **Output** | Markdown report with sections |
| **Sections** | Overview, Key Findings, Agent Analysis, Coalition Map, Predictions |
| **LLM** | Claude CLI — 5-15 calls (depends on depth) |
| **Cost** | ~$0.50-1.00 |
| **Files** | `app/services/report_agent.py` |

**Monitor:** `GET /api/report/{report_id}/progress`
**Chat:** `POST /api/report/chat` — interactive Q&A with report agent

---

## Stage 6: Interview

| Field | Value |
|-------|-------|
| **Component** | OASIS `ManualAction` + `ActionType.INTERVIEW` |
| **API** | `POST /api/simulation/interview` |
| **Input** | `agent_id` + prompt (question in Hebrew) |
| **Output** | Agent responds in-character based on persona + simulation history |
| **Modes** | Single, Batch (multiple agents), All |
| **LLM** | Claude CLI — 1 call per interview |
| **Cost** | ~$0.01 per interview |
| **Files** | `app/api/simulation.py`, `scripts/run_*_simulation.py` |

---

## Claude Analysis Chat

| Field | Value |
|-------|-------|
| **Component** | `ClaudeChatPanel` (Vue 3) + API endpoint |
| **API** | `POST /api/knesset/claude/chat` |
| **Input** | `message_he` + `simulation_id` + `simulation_state` |
| **Output** | `{text, mks[], voteTally{}, bills[]}` structured response |
| **Features** | Hebrew RTL, vote tally bars, MK references, session history |
| **Frontend** | Tab in KnessetSimulate.vue (next to live feed) |
| **Files** | `app/api/knesset.py`, `frontend/src/components/knesset/ClaudeChatPanel.vue` |

---

## Knesset-Specific Services

| Service | File | Purpose |
|---------|------|---------|
| **Orchestrator** | `knesset/orchestrator.py` | Full simulation lifecycle manager |
| **KnessetLoop** | `knesset/knesset_loop.py` | Round-by-round execution loop |
| **Multi-Model Router** | `knesset/multi_model_router.py` | Tiered LLM assignment per agent |
| **Batch Runner** | `knesset/batch_runner.py` | Parallel agent execution |
| **Chat Interface** | `knesset/chat_interface.py` | 1-on-1 and group MK chat |
| **Coalition Detector** | `knesset/coalition_detector.py` | Bloc detection + power mapping |
| **Prediction Validator** | `knesset/prediction_validator.py` | Predict → validate → calibrate |
| **Scenario Branching** | `knesset/scenario_branching.py` | Fork-and-compare simulations |
| **Live Data Feed** | `knesset/live_data_feed.py` | Real-time event injection |
| **Hebrew NLP** | `knesset/hebrew_nlp.py` | Hebrew text processing |
| **Voting Patterns** | `knesset/voting_patterns.py` | Historical vote analysis |
| **Parliament State** | `knesset/parliament_state.py` | Current Knesset state tracking |
| **Persona Generator** | `knesset/persona_generator.py` | MK persona creation |
| **Knesset Graph** | `knesset/knesset_graph.py` | Political knowledge graph |

---

## Shared Components (reusable across projects)

| Component | File | Purpose |
|-----------|------|---------|
| Entity Extractor | `system/T-tools/shared/entity_extractor.py` | LLM entity/relationship extraction |
| Graph Storage | `system/T-tools/shared/graph_storage.py` | Abstract storage + KuzuDB/JSON |
| Hybrid Search | `system/T-tools/shared/hybrid_search.py` | Qdrant + BM25 + RRF |
| Knowledge Pipeline | `system/T-tools/shared/knowledge_pipeline.py` | Document → knowledge extraction |
| LLM Client | `system/T-tools/shared/llm_client.py` | Multi-provider LLM client |
| Multi Retrieval | `system/T-tools/shared/multi_retrieval.py` | Advanced document retrieval |
| Ontology Generator | `system/T-tools/shared/ontology_generator.py` | Schema generation |
| ReACT Agent | `system/T-tools/shared/react_agent.py` | Autonomous reasoning agent |

---

## Cost Summary

| Stage | LLM Calls | Cost (Claude CLI) | Time |
|-------|-----------|-------------------|------|
| Documents | 0 | $0 | seconds |
| Ontology | 1 | ~$0.01 | 30s |
| Graph Build | 1-3/doc | ~$0.05 | 1-5 min |
| **Simulation** | **agents x rounds** | **$3-50** | **20 min - 10 hr** |
| Report | 5-15 | ~$0.50-1 | 5 min |
| Interview | 1/agent | ~$0.01/ea | 30s/ea |

**Optimization tips:**
- Use Multi-Model Tiering → 90% cost reduction on simulation
- Use Batch Parallel → 10x speed improvement
- Use Profile Caching → skip regeneration on repeat runs
- Use Live Data Feed → real-world accuracy
