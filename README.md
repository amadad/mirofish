# MiroFish

A swarm intelligence prediction engine. Feed it documents describing any scenario, and MiroFish simulates thousands of AI agents reacting on social media to predict how events will unfold.

> Fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) — fully translated to English, CLI-only, Claude/Codex CLI support added.

## What it does

1. **Feed reality seeds** — PDFs, markdown, or text files (news articles, policy drafts, financial reports, anything)
2. **Describe what to predict** — natural language requirement
3. **MiroFish builds a world** — extracts entities and relationships into a knowledge graph, generates AI agent personas with distinct personalities
4. **Agents simulate social media** — dual-platform simulation (Twitter + Reddit) where agents post, reply, like, argue, and follow each other
5. **Get a prediction report** — AI analyzes all simulation data and produces structured findings

## Quick start

### Prerequisites

- Python 3.11-3.12
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Setup

```bash
cp .env.example .env
# Default: claude-cli (uses your Claude Code subscription)
uv sync
```

### Run a simulation

```bash
mirofish run \
  --files docs/policy.pdf notes/context.md \
  --requirement "Predict public reaction over 30 days" \
  --json

# List prior runs
mirofish runs list --json

# Check run status
mirofish runs status <run_id> --json

# Export artifacts
mirofish runs export <run_id> --json
```

### CLI options

```
mirofish run
  --files FILE [FILE ...]     Source documents (PDF, markdown, text)
  --requirement TEXT          What to predict
  --platform parallel|twitter|reddit   Simulation platform (default: parallel)
  --max-rounds N              Max simulation rounds (default: 10)
  --output-dir PATH           Run output directory
  --json                      Machine-readable JSON output (stdout)
```

- Without `--json`: rich visual pipeline display on stderr
- With `--json`: machine-readable JSON on stdout, plain progress on stderr
- Exit code 0 = success, 1 = error

### Run artifacts

Each run produces an immutable directory:

```
uploads/runs/<run_id>/
  manifest.json
  input/
    requirement.txt
    source_files/
    ontology.json
    simulation_config.json
  graph/
    graph.json
    graph_summary.json
  simulation/
    timeline.json
    top_agents.json
    actions.jsonl
    config.json
  report/
    summary.json
    report.md
  visuals/
    swarm-overview.svg
    cluster-map.svg
    timeline.svg
    platform-split.svg
  logs/
    run.log
```

## LLM providers

Set `LLM_PROVIDER` in `.env`:

| Provider | Config | Cost |
|----------|--------|------|
| `claude-cli` | `LLM_PROVIDER=claude-cli` (default) | Uses your Claude Code subscription |
| `codex-cli` | `LLM_PROVIDER=codex-cli` | Uses your Codex CLI subscription |

## Architecture

```
app/
    cli.py             CLI entry point (primary interface)
    cli_display.py     Rich visual pipeline display
    config.py          Environment + validation
    run_artifacts.py   Immutable run storage
    visual_snapshots.py SVG snapshot generation
    core/              Workbench session, session registry, resource loader, tasks
    resources/         Adapters for projects, documents, graph, simulations, reports
    tools/             Composable pipeline (ingest, build, prepare, run, report)
    services/
      graph_storage.py     JSON graph backend
      graph_db.py          Graph query facade
      entity_extractor.py  LLM-based extraction
      graph_builder.py     Ontology -> graph pipeline
      simulation_runner.py OASIS simulation (subprocess)
      report_agent.py      Single-pass report generation
      graph_tools.py       Search, interview, analysis
    utils/
      llm_client.py        CLI-only LLM client (claude-cli, codex-cli)
  scripts/             OASIS simulation runner scripts
```

## Acknowledgments

- [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj — original project
- [OASIS](https://github.com/camel-ai/oasis) by CAMEL-AI — multi-agent social simulation framework

## License

AGPL-3.0
