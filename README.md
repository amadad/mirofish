# MiroFish

A social simulation scenario engine. Feed it documents describing any scenario, and MiroFish simulates AI agents reacting on social media to explore how events might unfold. Designed for agent-driven workflows — outputs include a machine-readable `verdict.json` alongside the full report.

> Fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) — fully translated to English, CLI-only, Claude/Codex CLI support added.

## What it does

1. **Feed reality seeds** — PDFs, markdown, or text files (news articles, policy drafts, financial reports, anything)
2. **Describe what to predict** — natural language requirement
3. **MiroFish builds a world** — extracts entities and relationships into a knowledge graph, generates AI agent personas with distinct personalities
4. **Agents simulate social media** — dual-platform simulation (Twitter + Reddit) where agents post, reply, like, argue, and follow each other
5. **Get a prediction report** — AI analyzes all simulation data and produces a report + machine-readable verdict with confidence scores and signals

## Quick start

### Prerequisites

- Python 3.11-3.12
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Setup

One-command bootstrap (installs uv if missing, creates `.env`, syncs
dependencies, checks your LLM provider CLI and runs `mirofish doctor`):

```bash
# macOS / Linux
./scripts/setup.sh                      # or: --provider codex-cli, --yes

# Windows (PowerShell)
.\scripts\setup.ps1                     # or: -Provider codex-cli, -Yes
# If script execution is disabled (stock Windows default):
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Or manually:

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

# List prior runs (slim summary: run_id, status, created_at, artifact_count)
mirofish runs list --json

# Check run status (full manifest)
mirofish runs status <run_id> --json

# Export artifacts
mirofish runs export <run_id> --json
```

### CLI options

```
mirofish run
  --files FILE [FILE ...]     Source files (pdf/md/txt) used to ground the
                              ontology and profiles
  --requirement TEXT          Plain-English simulation requirement
                              (e.g. "How would voters react to X?")
  --platform parallel|twitter|reddit   Simulation platform (default: parallel)
  --max-rounds N              Max simulation rounds (default: 10)
  --output-dir PATH           Run output directory
  --json                      Machine-readable JSON output (stdout)
```

- Without `--json`: rich visual pipeline display on stderr (respects `NO_COLOR` and non-tty stdout)
- With `--json`: machine-readable JSON on stdout, plain progress on stderr
- `--help` / `--version` work without a valid `.env`; other commands run `Config.validate()` first
- Exit code 0 = success, 1 = error (including config errors)

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
    verdict.json
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

Set `LLM_PROVIDER` in `.env`. Only `claude-cli` and `codex-cli` are accepted; any other value (e.g. `openai`) is rejected at startup with a `config error` and exit code 1.

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
