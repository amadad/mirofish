# CLAUDE.md

## What this is

MiroFish — CLI social simulation engine. Feed documents + a requirement, get a multi-agent social media simulation with report, verdict, and visual snapshots. Designed to be invoked by agents via the `mirofish` skill.

Fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish), fully translated to English.

## Commands

```bash
uv sync                                    # install
mirofish run --files f.pdf --requirement "..." --json   # run pipeline
mirofish runs list --json                  # list runs
mirofish runs status <id> --json           # check status
mirofish runs export <id> --json           # export artifacts
uv run python -m pytest -x                 # tests
```

## Layout

```
app/
  cli.py              Entry point (console_scripts: mirofish)
  config.py            Env + validation (.env loaded automatically)
  cli_display.py       Rich visual pipeline display
  run_artifacts.py     Immutable run storage (RunStore)
  visual_snapshots.py  SVG generation (no browser needed)
  core/                WorkbenchSession, TaskManager, ResourceLoader
  tools/               Composable pipeline steps (ontology, graph, prepare, run, report)
  services/            Business logic (graph_storage, simulation_runner, report_agent)
  resources/           Persistence adapters (projects, documents, graph, simulations, reports)
  models/              Data models
  utils/
    llm_client.py      CLI-only LLM client with retry (claude-cli, codex-cli)
    logger.py          Structured logging
scripts/               OASIS simulation runner scripts (subprocess)
tests/                 pytest
uploads/               Runtime data (gitignored)
data/                  Graph JSON storage (gitignored)
```

## Architecture

CLI (`cli.py`) orchestrates via `WorkbenchSession` which composes tools:
1. `GenerateOntologyTool` — LLM entity/relationship extraction from documents
2. `BuildGraphTool` — ontology → JSON graph (with entity validation against ontology types)
3. `PrepareSimulationTool` — agent profile generation (capped at 150 words)
4. `RunSimulationTool` — OASIS subprocess (Twitter + Reddit)
5. `GenerateReportTool` — single-pass report generation
6. Verdict generation — LLM extracts structured `verdict.json` from report

Each run produces an immutable directory under `uploads/runs/<run_id>/` with manifest, frozen inputs, graph, simulation data, report, verdict, SVG visuals, and logs.

### Key output: `report/verdict.json`

Machine-readable verdict for agent consumption — prediction, confidence (0-1), key_dynamics, and signals array. Agents should read this first, then `report/summary.json`, then `report/report.md` only if deeper analysis needed.

## Config

`.env` file at repo root. Key vars:
- `LLM_PROVIDER` — `claude-cli` (default) or `codex-cli`

## Agent Integration

Skill file: `~/agents/_skills/mirofish/SKILL.md`
Symlinked into `.claude/skills/` for discovery by Claude Code and OpenClaw agents.

## Gotchas
- Simulation runs OASIS in a subprocess via `scripts/`. The scripts add the project root to `sys.path` to import from `app.utils.oasis_llm`.
- `camel-oasis==0.2.5` and `camel-ai==0.2.78` are pinned — upgrading either can break the simulation pipeline.
- LLM calls have automatic retry with exponential backoff (3 attempts).
- CLI display (`cli_display.py`) uses `rich.Live` on stderr. Suppresses service-layer logs to WARNING during display. `--json` mode bypasses rich entirely.
- Never trash `uploads/runs/` — run artifacts are the product. Each run is immutable and self-contained.
- Process cleanup: `atexit` handler terminates OASIS subprocesses on CLI exit.
