# Multi-LLM Router + Search Upgrades — Design Doc

**Date**: 2026-03-23
**Status**: Approved
**Scope**: MiroFish backend — LLM routing, provider adapters, search upgrades, custom agent loop

---

## 1. Problem

MiroFish currently uses a single LLM provider for ALL tasks. This means:
- Agent decisions (400K calls) use expensive Claude/GPT — should use Groq ($0.03/M tokens)
- Report generation uses the same model as persona generation — should use Opus for depth
- Embeddings use a fallback model — should use BGE-M3 full (1.7GB, Hebrew-optimized)
- No cross-encoder reranking — missing 30-50% search accuracy improvement
- No parallelism across providers — one provider down = everything stops

## 2. Solution: Task-Based LLM Router

### 2.1 Router Architecture

New file: `backend/app/resources/llm/router.py`

```
User Request
    │
    ▼
LLM Router (reads llm_router.yaml)
    │
    ├── task_type: "agent_decision" → GroqAdapter → Llama 3.3 70B
    ├── task_type: "report"         → ClaudeAdapter → Opus
    ├── task_type: "ontology"       → ClaudeAdapter → Sonnet
    ├── task_type: "extraction"     → GPTAdapter → GPT-4o-mini
    ├── task_type: "persona"        → GroqAdapter → Llama 3.3 70B
    ├── task_type: "embedding"      → VLLMAdapter → BGE-M3 (local)
    └── task_type: "reranking"      → VLLMAdapter → cross-encoder (local)
```

Each task type has:
- Primary provider + model
- Fallback chain (e.g., Groq → GPT → Claude)
- Temperature, max_tokens, timeout
- Cost tracking (input/output tokens × price)

### 2.2 Config: `config/llm_router.yaml`

```yaml
providers:
  groq:
    type: openai_compatible
    base_url: https://api.groq.com/openai/v1
    api_key_env: GROQ_API_KEY
    rate_limit: 30  # requests/sec
    pricing:
      input: 0.59   # per 1M tokens
      output: 0.79

  openai:
    type: openai
    api_key_env: OPENAI_API_KEY
    rate_limit: 500
    pricing:
      input: 0.15  # gpt-4o-mini
      output: 0.60

  anthropic:
    type: anthropic
    api_key_env: LLM_API_KEY  # backward compatible
    rate_limit: 50
    pricing:
      input: 15.0  # opus
      output: 75.0

  vllm:
    type: openai_compatible
    base_url_env: VLLM_BASE_URL
    api_key: "dummy"  # vLLM doesn't need real key
    rate_limit: 100
    pricing:
      input: 0
      output: 0

routing:
  agent_decision:
    primary: { provider: groq, model: llama-3.3-70b-versatile }
    fallback: [{ provider: openai, model: gpt-4o-mini }]
    temperature: 0.7
    max_tokens: 256

  report:
    primary: { provider: anthropic, model: claude-opus-4-6 }
    fallback: [{ provider: openai, model: gpt-4o }]
    temperature: 0.5
    max_tokens: 4096

  ontology:
    primary: { provider: anthropic, model: claude-sonnet-4-5-20250929 }
    fallback: [{ provider: openai, model: gpt-4o }]
    temperature: 0.2
    max_tokens: 2048

  extraction:
    primary: { provider: groq, model: llama-3.3-70b-versatile }
    fallback: [{ provider: openai, model: gpt-4o-mini }]
    temperature: 0.2
    max_tokens: 2048

  persona:
    primary: { provider: groq, model: llama-3.3-70b-versatile }
    fallback: [{ provider: openai, model: gpt-4o-mini }]
    temperature: 0.8
    max_tokens: 512

  embedding:
    primary: { provider: vllm, model: BAAI/bge-m3 }
    fallback: [{ provider: local, model: intfloat/multilingual-e5-large }]

  reranking:
    primary: { provider: vllm, model: BAAI/bge-reranker-v2-m3 }
    fallback: [{ provider: local, model: cross-encoder/ms-marco-MiniLM-L-12-v2 }]
```

### 2.3 Provider Adapters

Extend existing `llm_client.py` with new adapters:

| Adapter | Base | Notes |
|---------|------|-------|
| `GroqAdapter` | OpenAI SDK with `base_url` override | Rate limit: 30 req/s free tier |
| `GPTAdapter` | Existing OpenAI code | Already works |
| `ClaudeAdapter` | Existing Anthropic code | Already works |
| `VLLMAdapter` | OpenAI SDK with custom `base_url` | For A100 instance |
| `LocalAdapter` | SentenceTransformers / HuggingFace | For embeddings when no vLLM |

All adapters implement:
```python
class LLMAdapter:
    async def complete(self, messages, **kwargs) -> str
    async def complete_json(self, messages, schema, **kwargs) -> dict
    async def embed(self, texts) -> list[list[float]]
    def estimate_cost(self, input_tokens, output_tokens) -> float
```

### 2.4 Cost Tracker

New file: `backend/app/resources/llm/cost_tracker.py`

Tracks per-simulation:
- Total calls per provider
- Total tokens (input/output) per provider
- Total cost estimate
- Stored in simulation state JSON

## 3. Search Upgrades

### 3.1 BGE-M3 Full Model

Current: Falls back to `intfloat/multilingual-e5-large` (560MB, 1024-dim)
Target: `BAAI/bge-m3` full (1.7GB, 1024-dim, trained on 100+ languages including Hebrew)

**Action**: Download model, update `hybrid_search.py` to use it as primary.

### 3.2 Cross-Encoder Reranking

Already stubbed in `hybrid_search.py` but not enabled.

**Action**:
- Enable `CrossEncoder` from sentence-transformers
- Model: `BAAI/bge-reranker-v2-m3` (multilingual, Hebrew-aware)
- Apply after hybrid search retrieval (top-50 → rerank → top-10)
- Expected improvement: +30-50% precision on Hebrew content

## 4. Custom Agent Loop (FastLoop)

New file: `backend/app/services/fast_agent_loop.py`

**Purpose**: Lightweight alternative to OASIS for high-volume simulations.

**Design**:
```python
class FastAgentLoop:
    """Async batch agent simulation — 10x faster than OASIS."""

    def __init__(self, router: LLMRouter, config: SimulationConfig):
        self.router = router
        self.agents = config.agents
        self.platform_state = PlatformState()  # in-memory Twitter/Reddit state

    async def run_round(self) -> list[AgentAction]:
        """Run one round: batch all agent decisions in parallel."""
        # Build prompts for all agents
        prompts = [self._build_prompt(agent) for agent in self.agents]
        # Batch call to Groq (50 agents per batch, async)
        responses = await self.router.batch_complete("agent_decision", prompts)
        # Parse actions, update platform state
        actions = [self._parse_action(r, agent) for r, agent in zip(responses, self.agents)]
        self.platform_state.apply(actions)
        return actions
```

**Key differences from OASIS**:
- No subprocess — runs in-process (Python async)
- Batch LLM calls (50-100 per request) vs sequential
- Simplified platform model (enough for narrative simulation, not full social media sim)
- 10x faster, 5x cheaper
- User selects engine at simulation start: "OASIS" or "FastLoop"

**Compatibility**: FastLoop outputs same `AgentAction` format as OASIS, so reports/analysis work with both.

## 5. .env Changes

```env
# Existing (backward compatible)
LLM_PROVIDER=anthropic
LLM_API_KEY=your_key
LLM_MODEL_NAME=claude-sonnet-4-20250514

# New multi-LLM
GROQ_API_KEY=gsk_...
OPENAI_API_KEY=sk-...
VLLM_BASE_URL=http://<a100-ip>:8000/v1

# Router config path
LLM_ROUTER_CONFIG=config/llm_router.yaml

# Search
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ENABLE_RERANKING=true
```

**Backward compatibility**: If `LLM_ROUTER_CONFIG` is not set, falls back to existing single-provider behavior.

## 6. File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `backend/app/resources/llm/router.py` | **NEW** | LLM Router with task-based routing |
| `backend/app/resources/llm/adapters.py` | **NEW** | Groq, vLLM, Local adapters |
| `backend/app/resources/llm/cost_tracker.py` | **NEW** | Per-simulation cost tracking |
| `config/llm_router.yaml` | **NEW** | Routing configuration |
| `backend/app/utils/llm_client.py` | **EDIT** | Add router integration, keep backward compat |
| `backend/app/services/hybrid_search.py` | **EDIT** | Enable reranking, BGE-M3 primary |
| `backend/app/services/fast_agent_loop.py` | **NEW** | Lightweight async agent loop |
| `backend/app/services/simulation_runner.py` | **EDIT** | Add FastLoop as engine option |
| `backend/app/config.py` | **EDIT** | Add new env vars |
| `.env.example` | **EDIT** | Document new env vars |
| `backend/app/api/simulation.py` | **EDIT** | Add engine selection to prepare/run endpoints |

## 7. Cost Model Per Simulation

| Component | Provider | Calls | Est. Cost |
|-----------|----------|-------|-----------|
| Agent decisions (400K) | Groq Llama 3.3 70B | 400,000 | ~$12.00 |
| Entity extraction | Groq Llama 3.3 70B | ~500 | ~$0.30 |
| Ontology generation | Claude Sonnet | 1 | ~$0.10 |
| Persona generation | Groq Llama 3.3 70B | ~100 | ~$0.05 |
| Report generation | Claude Opus | 1 | ~$0.50 |
| Embeddings | Local/vLLM BGE-M3 | ~5000 | $0.00 |
| **Total** | | | **~$13.00** |

vs current all-Claude: ~$50-80 per simulation.

## 8. Implementation Order

1. Router + Adapters (Groq, GPT, vLLM) — core infrastructure
2. Config YAML + backward compat in llm_client.py
3. Cost tracker
4. Search upgrades (BGE-M3 download + reranker enable)
5. FastLoop agent engine
6. API endpoint updates (engine selection)
7. Frontend: engine selector in simulation prepare UI
