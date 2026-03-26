import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.resources.llm.router import LLMRouter, RouteConfig


@pytest.fixture
def router_config_path(tmp_path):
    config = tmp_path / "llm_router.yaml"
    config.write_text("""
providers:
  mock_groq:
    type: openai_compatible
    base_url: "https://api.groq.com/openai/v1"
    api_key_env: GROQ_API_KEY
    rate_limit_rps: 30
    pricing_per_1m:
      input: 0.59
      output: 0.79
  mock_claude:
    type: anthropic
    api_key_env: LLM_API_KEY
    rate_limit_rps: 50
    pricing_per_1m:
      input: 15.0
      output: 75.0

routing:
  agent_decision:
    primary: { provider: mock_groq, model: "llama-3.3-70b" }
    fallback:
      - { provider: mock_claude, model: "claude-sonnet" }
    temperature: 0.7
    max_tokens: 256
  default:
    primary: { provider: mock_claude, model: "claude-sonnet" }
    fallback: []
    temperature: 0.7
    max_tokens: 4096
""")
    return str(config)


def test_load_config(router_config_path):
    router = LLMRouter(config_path=router_config_path)
    assert "mock_groq" in router.providers
    assert "mock_claude" in router.providers


def test_resolve_route(router_config_path):
    router = LLMRouter(config_path=router_config_path)
    route = router.resolve("agent_decision")
    assert route.provider_name == "mock_groq"
    assert route.model == "llama-3.3-70b"
    assert route.temperature == 0.7


def test_resolve_unknown_falls_to_default(router_config_path):
    router = LLMRouter(config_path=router_config_path)
    route = router.resolve("unknown_task")
    assert route.provider_name == "mock_claude"


def test_resolve_returns_fallback_chain(router_config_path):
    router = LLMRouter(config_path=router_config_path)
    route = router.resolve("agent_decision")
    assert len(route.fallbacks) == 1
    assert route.fallbacks[0]["provider"] == "mock_claude"
