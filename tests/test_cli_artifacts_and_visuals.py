import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli import _refresh_run_manifest, build_parser, main
from app.config import Config
from app.run_artifacts import RunStore
from app.services.simulation_runner import RunnerStatus, SimulationRunState
from app.visual_snapshots import generate_visual_snapshots


def test_run_store_persists_manifest_and_frozen_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))

    source_file = tmp_path / "seed.md"
    source_file.write_text("# Seed\n\nExample content", encoding="utf-8")

    store = RunStore()
    manifest = store.create("Predict the reaction", [str(source_file)], project_name="Demo")
    copied = store.freeze_source_files(manifest["run_id"], [str(source_file)])

    assert manifest["status"] == "created"
    assert len(copied) == 1
    assert Path(copied[0]).read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8")

    updated = store.update(manifest["run_id"], status="graph_ready", graph_id="graph_demo")
    assert updated["graph_id"] == "graph_demo"

    listed = store.list(limit=5)
    assert listed[0]["run_id"] == manifest["run_id"]


def test_generate_visual_snapshots_writes_svg_outputs(tmp_path: Path):
    graph_data = {
        "graph_id": "graph_demo",
        "node_count": 3,
        "edge_count": 2,
        "nodes": [
            {"uuid": "n1", "name": "Alice", "labels": ["Entity", "Citizen"]},
            {"uuid": "n2", "name": "Bob", "labels": ["Entity", "Citizen"]},
            {"uuid": "n3", "name": "University", "labels": ["Entity", "Institution"]},
        ],
        "edges": [
            {"source_node_uuid": "n1", "target_node_uuid": "n3"},
            {"source_node_uuid": "n2", "target_node_uuid": "n3"},
        ],
    }
    timeline = [
        {"round_num": 1, "twitter_actions": 3, "reddit_actions": 1, "total_actions": 4},
        {"round_num": 2, "twitter_actions": 2, "reddit_actions": 4, "total_actions": 6},
    ]

    artifacts = generate_visual_snapshots(graph_data, timeline, str(tmp_path / "visuals"))

    assert set(artifacts) == {"swarm_overview", "cluster_map", "timeline", "platform_split"}
    for path in artifacts.values():
        content = Path(path).read_text(encoding="utf-8")
        assert content.startswith("<svg")
        assert "font-family" in content


def test_generate_visual_snapshots_handles_empty_graph(tmp_path: Path):
    artifacts = generate_visual_snapshots({"nodes": [], "edges": []}, [], str(tmp_path / "visuals"))
    cluster_map = Path(artifacts["cluster_map"]).read_text(encoding="utf-8")

    assert "No graph nodes available" in cluster_map


def test_cli_parser_is_run_first():
    parser = build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))

    assert set(subparsers.choices) == {"run", "runs"}

    run_help = subparsers.choices["run"].format_help()
    assert "--files" in run_help
    assert "--requirement" in run_help
    assert "--project-name" not in run_help
    assert "--additional-context" not in run_help
    assert "--parallel-profile-count" not in run_help
    assert "--no-llm-profiles" not in run_help
    assert "--enable-graph-memory-update" not in run_help

    runs_subparsers = next(
        action for action in subparsers.choices["runs"]._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert set(runs_subparsers.choices) == {"list", "status", "export"}


def test_refresh_run_manifest_promotes_completed_simulation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))

    store = RunStore()
    manifest = store.create("Predict reaction", [], project_name="Status Demo")
    store.update(
        manifest["run_id"],
        status="simulation_running",
        simulation_id="sim_123",
    )

    state = SimulationRunState(
        simulation_id="sim_123",
        runner_status=RunnerStatus.COMPLETED,
        current_round=4,
        total_rounds=4,
    )
    monkeypatch.setattr("app.cli.SimulationRunner.get_run_state", lambda simulation_id: state)

    refreshed = _refresh_run_manifest(store, manifest["run_id"])

    assert refreshed["status"] == "simulation_completed"
    assert refreshed["task_progress"] == 100


def test_cli_runs_list_and_status_emit_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))

    store = RunStore()
    manifest = store.create("Predict reaction", [], project_name="List Demo")
    store.update(manifest["run_id"], status="graph_ready", graph_id="graph_123")
    store.write_text(manifest["run_id"], "visuals/swarm-overview.svg", "<svg />")
    store.record_artifact(manifest["run_id"], "swarm_overview", "visuals/swarm-overview.svg")

    exit_code = main(["runs", "list", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["runs"][0]["run_id"] == manifest["run_id"]

    exit_code = main(["runs", "status", manifest["run_id"], "--json"])
    captured = capsys.readouterr()
    status_payload = json.loads(captured.out)

    assert exit_code == 0
    assert status_payload["graph_id"] == "graph_123"
    assert status_payload["status"] == "graph_ready"

    exit_code = main(["runs", "export", manifest["run_id"], "--artifact", "swarm_overview", "--json"])
    captured = capsys.readouterr()
    export_payload = json.loads(captured.out)

    assert exit_code == 0
    assert export_payload["artifact"] == "swarm_overview"
    assert export_payload["path"].endswith("visuals/swarm-overview.svg")
