# MiroFish

A swarm intelligence prediction engine. Upload documents describing any scenario, and MiroFish simulates thousands of AI agents reacting on social media to predict how events will unfold.

**Live:** [synth.scty.org](https://synth.scty.org)
**Discord:** [discord.gg/ePf5aPaHnA](https://discord.gg/ePf5aPaHnA)

> Fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) — fully translated to English, local graph storage with embedded KuzuDB by default, Claude/Codex CLI support added.

## What it does

1. **Upload reality seeds** — PDFs, markdown, or text files (news articles, policy drafts, financial reports, anything)
2. **Describe what to predict** — natural language prompt (e.g., "Predict public reaction to this policy over 60 days")
3. **MiroFish builds a world** — extracts entities and relationships into a knowledge graph, generates AI agent personas with distinct personalities and opinions
4. **Agents simulate social media** — dual-platform simulation (Twitter + Reddit) where agents post, reply, like, argue, and follow each other
5. **Get a prediction report** — AI analyzes all simulation data and produces findings. Chat with the report agent or interview individual simulated agents.

## Changes from upstream

| Area | Upstream | This fork |
|------|----------|-----------|
| **Language** | Chinese UI + prompts | Full English (60+ files translated) |
| **LLM providers** | Alibaba Qwen only | OpenAI, Anthropic, Claude CLI, Codex CLI |
| **Graph database** | Hosted graph service | Local KuzuDB (embedded, free) |
| **Entity extraction** | Managed extraction pipeline | LLM-based extraction (uses your own model) |
| **Auth** | Requires API keys | Can use Claude Code or Codex CLI subscriptions (no separate API cost) |

## Quick start

### Prerequisites

- Node.js 18+
- Python 3.11-3.12
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Setup

```bash
cp .env.example .env
# Edit .env — pick your LLM provider (see below)
npm run setup:all
npm run dev
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:5001

### Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Docker builds the Vue frontend, serves it from the Flask app, and exposes the combined app on port `5001` inside the container.

## LLM providers

Set `LLM_PROVIDER` in `.env`:

| Provider | Config | Cost |
|----------|--------|------|
| `claude-cli` | Just set `LLM_PROVIDER=claude-cli` | Uses your Claude Code subscription |
| `codex-cli` | Just set `LLM_PROVIDER=codex-cli` | Uses your Codex CLI subscription |
| `openai` | Set `LLM_API_KEY` + `LLM_MODEL_NAME` | Pay-per-token |
| `anthropic` | Set `LLM_API_KEY` + `LLM_MODEL_NAME` | Pay-per-token |

```env
# Example: use Codex CLI (no API key needed)
LLM_PROVIDER=codex-cli

# Example: use OpenAI API
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL_NAME=gpt-4o-mini
```

## Using Codex CLI

For Docker deployments, MiroFish now routes Codex CLI traffic through a local OpenAI-compatible sidecar service at `codex-proxy`. The `mirofish` container talks to `http://codex-proxy:11435/v1`, and the proxy translates each `/v1/chat/completions` request into `codex exec --skip-git-repo-check` with bounded concurrency.

`docker-compose.yml` already wires this up for the Docker stack:

- `mirofish` runs with `LLM_PROVIDER=openai`
- `LLM_BASE_URL=http://codex-proxy:11435/v1`
- `LLM_API_KEY=codex`
- `LLM_MODEL_NAME=codex`
- `codex-proxy` uses `CODEX_PROXY_WORKERS=4` by default

To use it:

```bash
cp .env.example .env
docker compose up -d --build codex-proxy
curl http://localhost:11435/health
docker compose up -d
```

The proxy container mounts the host Codex binary and `~/.codex` auth state, so make sure Codex CLI is installed and authenticated on the host first. The legacy `LLM_PROVIDER=codex-cli` path remains available outside Docker as a fallback, but the proxy is the recommended Docker path because it queues requests instead of cold-starting an unbounded number of CLI subprocesses.

## Architecture

```
frontend/          Vue 3 + Vite + D3.js (graph visualization)
backend/
  app/
    api/           Thin Flask REST endpoints (graph, simulation, report)
    core/          Workbench session, session registry, resource loader, tasks
    resources/     Adapters for projects, documents, Kuzu, simulations, reports
    tools/         Composable workbench operations (ingest, build, prepare, run, report)
    services/
      graph_storage.py     GraphStorage abstraction + KuzuDB/JSON backends
      graph_db.py          Compatibility facade over per-graph storage backends
      entity_extractor.py  LLM-based entity/relationship extraction
      graph_builder.py     Ontology → graph pipeline
      simulation_runner.py OASIS multi-agent simulation (subprocess)
      report_agent.py      ReACT agent with tool-calling for reports
      graph_tools.py       Search, interview, and analysis tools
    utils/
      llm_client.py        Multi-provider LLM client (OpenAI/Anthropic/CLI)
  scripts/         OASIS simulation runner scripts (Twitter + Reddit)
```

Workbench session metadata is persisted under `backend/uploads/workbench_sessions/`, and long-running task state is persisted under `backend/uploads/tasks/`.

The backend is being refactored toward a pi-style shape: one workbench session core, pluggable resource adapters, composable tools, and thin API shells.

## How the pipeline works

```
Document upload → LLM ontology extraction → Knowledge graph (GraphStorage → KuzuDB by default)
    → Entity filtering → Agent persona generation (LLM)
    → OASIS dual-platform simulation (Twitter + Reddit subprocess)
    → Graph memory updates → Report generation (ReACT agent)
    → Interactive chat with report agent or individual agents
```

## Acknowledgments

- [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj — original project
- [OASIS](https://github.com/camel-ai/oasis) by CAMEL-AI — multi-agent social simulation framework
- [KuzuDB](https://github.com/kuzudb/kuzu) — embedded graph database

## License

AGPL-3.0
License

AGPL-3.0
