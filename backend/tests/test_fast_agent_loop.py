import pytest
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.fast_agent_loop import FastAgentLoop, AgentPersona, PlatformState


def test_platform_state_apply_post():
    state = PlatformState()
    state.apply_action("agent_1", "Alice", "CREATE_POST", {"content": "Hello world"})
    assert len(state.posts) == 1
    assert state.posts[0]["author"] == "Alice"


def test_build_prompt_includes_persona():
    persona = AgentPersona(
        agent_id="a1", name="Alice", role="Journalist",
        background="Investigative reporter", personality="skeptical",
        stances={"media": "critical"}, platform="twitter",
    )
    state = PlatformState()
    loop = FastAgentLoop.__new__(FastAgentLoop)
    loop.platform_state = state
    loop.max_rounds = 10
    prompt = loop._build_prompt(persona, round_num=1)
    assert "Alice" in prompt
    assert "Journalist" in prompt
    assert "skeptical" in prompt


@pytest.mark.asyncio
async def test_run_round_returns_actions():
    mock_router = MagicMock()
    mock_router.chat.return_value = '{"action": "CREATE_POST", "content": "Test post"}'

    personas = [
        AgentPersona("a1", "Alice", "Reporter", "Background", "bold", {}, "twitter"),
    ]
    loop = FastAgentLoop(router=mock_router, personas=personas, max_rounds=1)
    actions = await loop.run_round(round_num=1)
    assert len(actions) == 1
    assert actions[0].agent_name == "Alice"
