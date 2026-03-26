import pytest
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.agent_memory import AgentMemoryStore, AgentMemoryState, MemoryEntry


@pytest.fixture
def store(tmp_path):
    return AgentMemoryStore("test_project", base_dir=str(tmp_path))


def test_load_new_agent(store):
    state = store.load("agent_1", agent_name="Alice")
    assert state.agent_id == "agent_1"
    assert state.agent_name == "Alice"
    assert state.total_simulations == 0
    assert len(state.beliefs) == 0


def test_save_and_reload(store):
    state = store.load("agent_1", agent_name="Alice")
    state.beliefs.append(MemoryEntry(
        content="Markets are bearish",
        source="observation",
        strength=0.8,
    ))
    store.save(state)

    reloaded = store.load("agent_1")
    assert len(reloaded.beliefs) == 1
    assert reloaded.beliefs[0].content == "Markets are bearish"
    assert reloaded.beliefs[0].strength == 0.8


def test_memory_decay(store):
    state = store.load("agent_1", agent_name="Alice")
    state.beliefs.append(MemoryEntry(content="Old belief", source="observation", strength=0.5))
    state.beliefs.append(MemoryEntry(content="Strong belief", source="observation", strength=1.0))
    store.save(state)

    # Simulate processing results with decay
    actions = [
        {"agent_id": "agent_1", "agent_name": "Alice", "action_type": "CREATE_POST",
         "action_args": {"content": "New post"}, "round_num": 1, "timestamp": "2026-01-01T00:00:00"},
    ]
    store.save_simulation_results("sim_1", actions, decay_factor=0.5)

    reloaded = store.load("agent_1")
    # Old belief at 0.5 * 0.5 = 0.25 — still above 0.1 threshold
    # Strong belief at 1.0 * 0.5 = 0.5
    assert len(reloaded.beliefs) == 2
    assert reloaded.beliefs[0].strength == pytest.approx(0.25)
    assert reloaded.beliefs[1].strength == pytest.approx(0.5)
    assert reloaded.total_simulations == 1


def test_weak_memories_pruned(store):
    state = store.load("agent_1", agent_name="Alice")
    state.beliefs.append(MemoryEntry(content="Very weak", source="observation", strength=0.05))
    store.save(state)

    actions = [{"agent_id": "agent_1", "agent_name": "Alice", "action_type": "DO_NOTHING",
                "round_num": 1, "timestamp": ""}]
    store.save_simulation_results("sim_1", actions, decay_factor=0.9)

    reloaded = store.load("agent_1")
    # 0.05 * 0.9 = 0.045 < 0.1 threshold — should be pruned
    assert len(reloaded.beliefs) == 0


def test_context_summary(store):
    state = store.load("agent_1", agent_name="Alice")
    state.total_simulations = 3
    state.beliefs.append(MemoryEntry(content="I distrust the media", source="belief", strength=0.9))
    state.relationships.append(MemoryEntry(content="Allied with Bob on economic issues", source="relationship", strength=0.8))
    state.actions_history.append(MemoryEntry(content="CREATE_POST: The economy is failing", source="action"))

    summary = state.get_context_summary()
    assert "3 previous simulations" in summary
    assert "distrust the media" in summary
    assert "Allied with Bob" in summary
    assert "economy is failing" in summary


def test_list_agents(store):
    store.save(AgentMemoryState(agent_id="a1", agent_name="Alice"))
    store.save(AgentMemoryState(agent_id="a2", agent_name="Bob"))
    agents = store.list_agents()
    assert set(agents) == {"a1", "a2"}


def test_clear(store):
    store.save(AgentMemoryState(agent_id="a1", agent_name="Alice"))
    store.save(AgentMemoryState(agent_id="a2", agent_name="Bob"))
    cleared = store.clear()
    assert cleared == 2
    assert store.list_agents() == []


def test_serialization_roundtrip():
    state = AgentMemoryState(
        agent_id="test", agent_name="Test Agent",
        role="journalist", personality="skeptical",
        total_simulations=5, total_actions=100,
    )
    state.beliefs.append(MemoryEntry(content="Test belief", source="belief", strength=0.7))

    data = state.to_dict()
    json_str = json.dumps(data)
    restored = AgentMemoryState.from_dict(json.loads(json_str))

    assert restored.agent_id == "test"
    assert restored.total_simulations == 5
    assert len(restored.beliefs) == 1
    assert restored.beliefs[0].strength == 0.7
