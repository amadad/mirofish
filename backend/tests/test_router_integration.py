"""Integration test: router -> provider -> cost tracking."""
import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.resources.llm.router import LLMRouter


@pytest.fixture
def mock_env(tmp_path):
    config = tmp_path / "router.yaml"
    config.write_text("""
providers:
  test_groq:
    type: openai_compatible
    base_url: "https://api.groq.com/openai/v1"
    api_key: "test-key"
    pricing_per_1m:
      input: 0.59
      output: 0.79
routing:
  agent_decision:
    primary: { provider: test_groq, model: "llama-3.3-70b" }
    fallback: []
    temperature: 0.7
    max_tokens: 256
  default:
    primary: { provider: test_groq, model: "llama-3.3-70b" }
    fallback: []
    temperature: 0.7
    max_tokens: 4096
""")
    return str(config)


def test_router_tracks_cost(mock_env):
    router = LLMRouter(config_path=mock_env)
    mock_client = MagicMock()
    mock_client.chat.return_value = "test response"
    mock_client.model = "llama"
    router._clients["test_groq"] = mock_client

    result = router.chat("agent_decision", [{"role": "user", "content": "test"}])
    assert result == "test response"

    summary = router.cost_tracker.summary()
    assert summary["total_calls"] == 1
    assert "test_groq" in summary["providers"]


def test_router_fallback_on_failure(mock_env):
    """When primary fails, router should try fallback."""
    router = LLMRouter(config_path=mock_env)

    # No client registered = will fail to get_client
    # Since there's no fallback, should raise
    with pytest.raises(RuntimeError, match="All providers failed"):
        router.chat("agent_decision", [{"role": "user", "content": "test"}])


def test_router_json_tracks_cost(mock_env):
    router = LLMRouter(config_path=mock_env)
    mock_client = MagicMock()
    mock_client.chat_json.return_value = {"key": "value"}
    mock_client.model = "llama"
    router._clients["test_groq"] = mock_client

    result = router.chat_json("agent_decision", [{"role": "user", "content": "test"}])
    assert result == {"key": "value"}
    assert router.cost_tracker.summary()["total_calls"] == 1
