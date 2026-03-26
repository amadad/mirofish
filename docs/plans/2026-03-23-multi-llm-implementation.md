# Multi-LLM Router + Search Upgrades — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add task-based LLM routing (Groq, GPT, vLLM, Claude) with cost tracking, enable BGE-M3 + cross-encoder reranking, and scaffold a FastLoop agent engine.

**Architecture:** A YAML-driven router maps each task type (agent_decision, report, extraction, etc.) to the optimal provider/model. Provider adapters wrap OpenAI-compatible APIs (Groq, vLLM) and existing clients (Claude, GPT). The router slots into the existing `LLMProvider` → `LLMClient` chain with full backward compatibility.

**Tech Stack:** Python 3.11+, PyYAML, OpenAI SDK, Anthropic SDK, sentence-transformers, asyncio

---

## Task 1: Router Config YAML

**Files:**
- Create: `backend/config/llm_router.yaml`

**Step 1: Create the config directory and YAML file**

```yaml
# backend/config/llm_router.yaml
providers:
  groq:
    type: openai_compatible
    base_url: "https://api.groq.com/openai/v1"
    api_key_env: GROQ_API_KEY
    rate_limit_rps: 30
    pricing_per_1m:
      input: 0.59
      output: 0.79

  openai:
    type: openai
    api_key_env: OPENAI_API_KEY
    base_url: "https://api.openai.com/v1"
    rate_limit_rps: 500
    pricing_per_1m:
      input: 0.15
      output: 0.60

  anthropic:
    type: anthropic
    api_key_env: LLM_API_KEY
    rate_limit_rps: 50
    pricing_per_1m:
      input: 15.0
      output: 75.0

  anthropic_sonnet:
    type: anthropic
    api_key_env: LLM_API_KEY
    rate_limit_rps: 50
    pricing_per_1m:
      input: 3.0
      output: 15.0

  vllm:
    type: openai_compatible
    base_url_env: VLLM_BASE_URL
    api_key: "dummy"
    rate_limit_rps: 100
    pricing_per_1m:
      input: 0
      output: 0

routing:
  agent_decision:
    primary: { provider: groq, model: "llama-3.3-70b-versatile" }
    fallback:
      - { provider: openai, model: "gpt-4o-mini" }
    temperature: 0.7
    max_tokens: 256

  report:
    primary: { provider: anthropic, model: "claude-opus-4-6" }
    fallback:
      - { provider: openai, model: "gpt-4o" }
    temperature: 0.5
    max_tokens: 4096

  ontology:
    primary: { provider: anthropic_sonnet, model: "claude-sonnet-4-5-20250929" }
    fallback:
      - { provider: openai, model: "gpt-4o" }
    temperature: 0.2
    max_tokens: 2048

  extraction:
    primary: { provider: groq, model: "llama-3.3-70b-versatile" }
    fallback:
      - { provider: openai, model: "gpt-4o-mini" }
    temperature: 0.2
    max_tokens: 2048

  persona:
    primary: { provider: groq, model: "llama-3.3-70b-versatile" }
    fallback:
      - { provider: openai, model: "gpt-4o-mini" }
    temperature: 0.8
    max_tokens: 512

  default:
    primary: { provider: anthropic_sonnet, model: "claude-sonnet-4-5-20250929" }
    fallback:
      - { provider: openai, model: "gpt-4o-mini" }
    temperature: 0.7
    max_tokens: 4096
```

**Step 2: Commit**

```bash
git add backend/config/llm_router.yaml
git commit -m "feat: add LLM router configuration YAML"
```

---

## Task 2: Cost Tracker

**Files:**
- Create: `backend/app/resources/llm/cost_tracker.py`
- Create: `backend/tests/test_cost_tracker.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_cost_tracker.py
import pytest
from app.resources.llm.cost_tracker import CostTracker


def test_record_call_tracks_tokens():
    tracker = CostTracker()
    tracker.record("groq", "llama-3.3-70b-versatile", input_tokens=1000, output_tokens=500)
    summary = tracker.summary()
    assert summary["total_calls"] == 1
    assert summary["providers"]["groq"]["calls"] == 1
    assert summary["providers"]["groq"]["input_tokens"] == 1000
    assert summary["providers"]["groq"]["output_tokens"] == 500


def test_cost_estimation():
    tracker = CostTracker()
    tracker.set_pricing("groq", input_per_1m=0.59, output_per_1m=0.79)
    tracker.record("groq", "llama-3.3-70b-versatile", input_tokens=1_000_000, output_tokens=1_000_000)
    summary = tracker.summary()
    assert abs(summary["providers"]["groq"]["estimated_cost"] - 1.38) < 0.01


def test_multiple_providers():
    tracker = CostTracker()
    tracker.set_pricing("groq", input_per_1m=0.59, output_per_1m=0.79)
    tracker.set_pricing("anthropic", input_per_1m=15.0, output_per_1m=75.0)
    tracker.record("groq", "llama", input_tokens=100, output_tokens=50)
    tracker.record("anthropic", "opus", input_tokens=200, output_tokens=100)
    summary = tracker.summary()
    assert summary["total_calls"] == 2
    assert len(summary["providers"]) == 2


def test_to_dict_serializable():
    tracker = CostTracker()
    tracker.record("groq", "llama", input_tokens=10, output_tokens=5)
    import json
    json.dumps(tracker.summary())  # Should not raise
```

**Step 2: Run test to verify it fails**

Run: `cd MIROFISH/backend && python -m pytest tests/test_cost_tracker.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# backend/app/resources/llm/cost_tracker.py
"""Per-simulation LLM cost tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ProviderStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0

    @property
    def estimated_cost(self) -> float:
        return (
            self.input_tokens * self.input_price_per_1m / 1_000_000
            + self.output_tokens * self.output_price_per_1m / 1_000_000
        )


class CostTracker:
    """Track LLM usage and cost across providers for a single simulation."""

    def __init__(self):
        self._providers: Dict[str, ProviderStats] = {}

    def set_pricing(self, provider: str, input_per_1m: float, output_per_1m: float) -> None:
        stats = self._providers.setdefault(provider, ProviderStats())
        stats.input_price_per_1m = input_per_1m
        stats.output_price_per_1m = output_per_1m

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        stats = self._providers.setdefault(provider, ProviderStats())
        stats.calls += 1
        stats.input_tokens += input_tokens
        stats.output_tokens += output_tokens

    def summary(self) -> dict:
        providers = {}
        total_cost = 0.0
        total_calls = 0
        for name, stats in self._providers.items():
            cost = stats.estimated_cost
            total_cost += cost
            total_calls += stats.calls
            providers[name] = {
                "calls": stats.calls,
                "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens,
                "estimated_cost": round(cost, 4),
            }
        return {
            "total_calls": total_calls,
            "total_estimated_cost": round(total_cost, 4),
            "providers": providers,
        }
```

**Step 4: Run test to verify it passes**

Run: `cd MIROFISH/backend && python -m pytest tests/test_cost_tracker.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add backend/app/resources/llm/cost_tracker.py backend/tests/test_cost_tracker.py
git commit -m "feat: add LLM cost tracker with per-provider stats"
```

---

## Task 3: LLM Router Core

**Files:**
- Create: `backend/app/resources/llm/router.py`
- Create: `backend/tests/test_llm_router.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_llm_router.py
import pytest
import os
from unittest.mock import patch, MagicMock
from app.resources.llm.router import LLMRouter, RouteConfig


@pytest.fixture
def router_config_path(tmp_path):
    """Create a minimal router config for testing."""
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
```

**Step 2: Run test to verify it fails**

Run: `cd MIROFISH/backend && python -m pytest tests/test_llm_router.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# backend/app/resources/llm/router.py
"""Task-based LLM router — maps task types to optimal providers."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .cost_tracker import CostTracker

logger = logging.getLogger("mirofish.llm_router")


@dataclass
class ProviderConfig:
    name: str
    type: str  # "openai_compatible", "anthropic", "openai"
    base_url: str = ""
    api_key: str = ""
    rate_limit_rps: int = 50
    pricing_input: float = 0.0
    pricing_output: float = 0.0


@dataclass
class RouteConfig:
    provider_name: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    fallbacks: List[Dict[str, str]] = field(default_factory=list)


class LLMRouter:
    """Routes LLM calls to the optimal provider based on task type."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.environ.get(
            "LLM_ROUTER_CONFIG",
            os.path.join(os.path.dirname(__file__), "../../../config/llm_router.yaml"),
        )
        self.providers: Dict[str, ProviderConfig] = {}
        self._routes: Dict[str, dict] = {}
        self.cost_tracker = CostTracker()
        self._clients: Dict[str, Any] = {}

        if os.path.exists(self.config_path):
            self._load_config()
        else:
            logger.warning("Router config not found at %s — using defaults", self.config_path)

    def _load_config(self) -> None:
        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # Parse providers
        for name, prov in raw.get("providers", {}).items():
            base_url = prov.get("base_url", "")
            if not base_url:
                env_key = prov.get("base_url_env", "")
                base_url = os.environ.get(env_key, "") if env_key else ""

            api_key = prov.get("api_key", "")
            if not api_key:
                env_key = prov.get("api_key_env", "")
                api_key = os.environ.get(env_key, "") if env_key else ""

            pricing = prov.get("pricing_per_1m", {})

            self.providers[name] = ProviderConfig(
                name=name,
                type=prov.get("type", "openai_compatible"),
                base_url=base_url,
                api_key=api_key,
                rate_limit_rps=prov.get("rate_limit_rps", 50),
                pricing_input=pricing.get("input", 0.0),
                pricing_output=pricing.get("output", 0.0),
            )
            self.cost_tracker.set_pricing(
                name,
                input_per_1m=pricing.get("input", 0.0),
                output_per_1m=pricing.get("output", 0.0),
            )

        # Parse routes
        self._routes = raw.get("routing", {})
        logger.info(
            "Loaded router config: %d providers, %d routes",
            len(self.providers),
            len(self._routes),
        )

    def resolve(self, task_type: str) -> RouteConfig:
        """Resolve a task type to a RouteConfig."""
        route_raw = self._routes.get(task_type) or self._routes.get("default", {})
        primary = route_raw.get("primary", {})
        return RouteConfig(
            provider_name=primary.get("provider", ""),
            model=primary.get("model", ""),
            temperature=route_raw.get("temperature", 0.7),
            max_tokens=route_raw.get("max_tokens", 4096),
            fallbacks=route_raw.get("fallback", []),
        )

    def get_client(self, provider_name: str):
        """Get or create an LLMClient for a provider. Returns the existing LLMClient."""
        if provider_name in self._clients:
            return self._clients[provider_name]

        prov = self.providers.get(provider_name)
        if not prov:
            raise ValueError(f"Unknown provider: {provider_name}")

        from ...utils.llm_client import LLMClient

        if prov.type == "anthropic":
            client = LLMClient(
                api_key=prov.api_key,
                provider="anthropic",
            )
        elif prov.type in ("openai", "openai_compatible"):
            client = LLMClient(
                api_key=prov.api_key or "dummy",
                base_url=prov.base_url or None,
                provider="openai",
            )
        else:
            raise ValueError(f"Unknown provider type: {prov.type}")

        self._clients[provider_name] = client
        return client

    def chat(
        self,
        task_type: str,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Route a chat call to the right provider based on task type."""
        route = self.resolve(task_type)
        providers_to_try = [
            {"provider": route.provider_name, "model": route.model}
        ] + route.fallbacks

        last_error = None
        for attempt in providers_to_try:
            prov_name = attempt["provider"]
            model = attempt["model"]
            try:
                client = self.get_client(prov_name)
                client.model = model
                result = client.chat(
                    messages=messages,
                    temperature=temperature if temperature is not None else route.temperature,
                    max_tokens=max_tokens if max_tokens is not None else route.max_tokens,
                )
                # Estimate tokens (rough: 4 chars per token)
                input_text = " ".join(m.get("content", "") for m in messages)
                input_tokens = len(input_text) // 4
                output_tokens = len(result) // 4
                self.cost_tracker.record(prov_name, model, input_tokens, output_tokens)
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider %s failed for task %s: %s — trying fallback",
                    prov_name, task_type, e,
                )

        raise RuntimeError(
            f"All providers failed for task '{task_type}': {last_error}"
        )

    def chat_json(
        self,
        task_type: str,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """Route a JSON chat call with structured output."""
        route = self.resolve(task_type)
        providers_to_try = [
            {"provider": route.provider_name, "model": route.model}
        ] + route.fallbacks

        last_error = None
        for attempt in providers_to_try:
            prov_name = attempt["provider"]
            model = attempt["model"]
            try:
                client = self.get_client(prov_name)
                client.model = model
                result = client.chat_json(
                    messages=messages,
                    temperature=temperature if temperature is not None else route.temperature,
                    max_tokens=max_tokens if max_tokens is not None else route.max_tokens,
                )
                input_text = " ".join(m.get("content", "") for m in messages)
                input_tokens = len(input_text) // 4
                output_tokens = 500  # rough estimate for JSON
                self.cost_tracker.record(prov_name, model, input_tokens, output_tokens)
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider %s JSON failed for task %s: %s — trying fallback",
                    prov_name, task_type, e,
                )

        raise RuntimeError(
            f"All providers failed for JSON task '{task_type}': {last_error}"
        )
```

**Step 4: Run tests**

Run: `cd MIROFISH/backend && python -m pytest tests/test_llm_router.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add backend/app/resources/llm/router.py backend/tests/test_llm_router.py
git commit -m "feat: add task-based LLM router with fallback chains"
```

---

## Task 4: Update Config + .env

**Files:**
- Modify: `backend/app/config.py:57-61` — add new env vars
- Modify: `MIROFISH/.env.example:1-41` — add multi-LLM section

**Step 1: Add new config vars to `config.py`**

After line 61 (`LLM_PROVIDER = ...`), add:

```python
    # Multi-LLM routing
    LLM_ROUTER_CONFIG = os.environ.get("LLM_ROUTER_CONFIG", "")
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "")

    # Search config
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")
    RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    ENABLE_RERANKING = _get_bool_env("ENABLE_RERANKING", True)
```

**Step 2: Update `.env.example`**

Append after line 41:

```env

# ===== Multi-LLM Routing (optional) =====
# When LLM_ROUTER_CONFIG is set, task-based routing activates.
# Each task type (agent_decision, report, extraction, etc.) can use a different provider.
# Without this, falls back to single-provider mode (LLM_PROVIDER above).
# LLM_ROUTER_CONFIG=config/llm_router.yaml

# Groq (fast + cheap for agent decisions)
# GROQ_API_KEY=gsk_your_groq_key_here

# OpenAI (fallback + entity extraction)
# OPENAI_API_KEY=sk-your_openai_key_here

# vLLM on A100 (embeddings + reranking, zero cost)
# VLLM_BASE_URL=http://your-a100-ip:8000/v1

# ===== Search Configuration =====
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
ENABLE_RERANKING=true
```

**Step 3: Commit**

```bash
git add backend/app/config.py .env.example
git commit -m "feat: add multi-LLM env vars and search config"
```

---

## Task 5: Wire Router into LLMProvider

**Files:**
- Modify: `backend/app/resources/llm/provider.py` — add router support
- Modify: `backend/app/resources/llm/__init__.py` — export router

**Step 1: Update `provider.py` to use router when available**

Replace entire file with:

```python
# backend/app/resources/llm/provider.py
"""LLM provider adapter — supports single-provider and routed mode."""

from typing import Any, Dict, List, Optional

from ...config import Config
from ...utils.llm_client import LLMClient


class LLMProvider:
    """Thin adapter around the configured LLM client.

    When LLM_ROUTER_CONFIG is set, delegates to the router.
    Otherwise, uses the single LLMClient as before.
    """

    def __init__(self, client: Optional[LLMClient] = None):
        self._router = None
        self.client = client or LLMClient()

        # Try to initialize router if config is set
        if Config.LLM_ROUTER_CONFIG:
            try:
                from .router import LLMRouter
                self._router = LLMRouter(Config.LLM_ROUTER_CONFIG)
            except Exception as e:
                import logging
                logging.getLogger("mirofish.llm_provider").warning(
                    "Failed to init router: %s — using single provider", e
                )

    @property
    def is_routed(self) -> bool:
        return self._router is not None

    @property
    def router(self):
        return self._router

    @property
    def provider_name(self) -> str:
        return self.client.provider or Config.LLM_PROVIDER or "openai"

    @property
    def model_name(self) -> str:
        return self.client.model or Config.LLM_MODEL_NAME

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, Any]] = None,
        task_type: str = "default",
    ) -> str:
        if self._router and task_type != "default":
            return self._router.chat(
                task_type=task_type,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return self.client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        task_type: str = "default",
    ) -> dict:
        if self._router and task_type != "default":
            return self._router.chat_json(
                task_type=task_type,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return self.client.chat_json(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
```

**Step 2: Update `__init__.py` exports**

```python
# backend/app/resources/llm/__init__.py
from .provider import LLMProvider
from .cost_tracker import CostTracker

__all__ = ["LLMProvider", "CostTracker"]
```

**Step 3: Commit**

```bash
git add backend/app/resources/llm/provider.py backend/app/resources/llm/__init__.py
git commit -m "feat: wire LLM router into LLMProvider with backward compat"
```

---

## Task 6: Add `task_type` to Service Callers

**Files:**
- Modify: `backend/app/services/entity_extractor.py` — add `task_type="extraction"`
- Modify: `backend/app/services/ontology_generator.py` — add `task_type="ontology"`
- Modify: `backend/app/services/oasis_profile_generator.py` — add `task_type="persona"`
- Modify: `backend/app/services/report_agent.py` — add `task_type="report"`

For each service, find the `llm.chat()` or `llm.chat_json()` calls and add the `task_type` kwarg. The existing `LLMProvider.chat()` signature now accepts `task_type` with default `"default"`, so unchanged callers continue to work.

**Step 1: Update entity_extractor.py**

Search for `self.llm.chat_json(` or `self.llm.chat(` calls. Add `task_type="extraction"` as kwarg.

**Step 2: Update ontology_generator.py**

Same pattern — add `task_type="ontology"`.

**Step 3: Update oasis_profile_generator.py**

Add `task_type="persona"`.

**Step 4: Update report_agent.py**

Add `task_type="report"`.

**Step 5: Verify app starts**

Run: `cd MIROFISH && npm run dev:backend`
Expected: Server starts on :5001 without errors

**Step 6: Commit**

```bash
git add backend/app/services/entity_extractor.py backend/app/services/ontology_generator.py \
    backend/app/services/oasis_profile_generator.py backend/app/services/report_agent.py
git commit -m "feat: wire task_type routing into all LLM service callers"
```

---

## Task 7: Enable Reranking in Hybrid Search

**Files:**
- Modify: `backend/app/services/hybrid_search.py:318` — read config for reranking toggle

**Step 1: Update search() default to read from Config**

In `hybrid_search.py`, modify the `search()` method signature at line 310:

Change:
```python
    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "both",
        include_expired: bool = False,
        semantic_weight: Optional[float] = None,
        rerank: bool = True,
    ) -> list[HybridResult]:
```

To:
```python
    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "both",
        include_expired: bool = False,
        semantic_weight: Optional[float] = None,
        rerank: Optional[bool] = None,
    ) -> list[HybridResult]:
```

And at line 335, add:
```python
        if rerank is None:
            from ..config import Config
            rerank = getattr(Config, "ENABLE_RERANKING", True)
```

**Step 2: Update the `__init__` to use configured embedding model**

At line 131, change:
```python
        model_name: str = DEFAULT_MODEL,
```

To:
```python
        model_name: Optional[str] = None,
```

And in `__init__` body:
```python
        from ..config import Config
        self.model_name = model_name or getattr(Config, "EMBEDDING_MODEL", DEFAULT_MODEL)
```

**Step 3: Commit**

```bash
git add backend/app/services/hybrid_search.py
git commit -m "feat: enable config-driven reranking and embedding model"
```

---

## Task 8: FastLoop Agent Engine (Scaffold)

**Files:**
- Create: `backend/app/services/fast_agent_loop.py`
- Create: `backend/tests/test_fast_agent_loop.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_fast_agent_loop.py
import pytest
from unittest.mock import MagicMock, AsyncMock
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
```

**Step 2: Run test to verify it fails**

Run: `cd MIROFISH/backend && python -m pytest tests/test_fast_agent_loop.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# backend/app/services/fast_agent_loop.py
"""FastLoop — lightweight async agent simulation engine.

Alternative to OASIS for high-volume simulations.
Optimized for Groq throughput: batches agent decisions, runs in-process.
Outputs same AgentAction format as OASIS runner for report compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.fast_agent_loop")

TWITTER_ACTIONS = [
    "CREATE_POST", "LIKE_POST", "REPOST", "FOLLOW", "QUOTE_POST", "DO_NOTHING"
]


@dataclass
class AgentPersona:
    agent_id: str
    name: str
    role: str
    background: str
    personality: str
    stances: Dict[str, str]
    platform: str = "twitter"


@dataclass
class AgentAction:
    round_num: int
    timestamp: str
    platform: str
    agent_id: str
    agent_name: str
    action_type: str
    action_args: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    success: bool = True

    def to_dict(self) -> dict:
        return {
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_type": self.action_type,
            "action_args": self.action_args,
            "result": self.result,
            "success": self.success,
        }


class PlatformState:
    """In-memory social media state for FastLoop."""

    def __init__(self):
        self.posts: List[Dict] = []
        self.likes: Dict[str, int] = {}  # post_id -> count
        self.follows: List[Dict] = []

    def apply_action(self, agent_id: str, agent_name: str, action_type: str, args: dict) -> None:
        if action_type == "CREATE_POST":
            post_id = f"post_{len(self.posts)}"
            self.posts.append({
                "id": post_id,
                "author": agent_name,
                "author_id": agent_id,
                "content": args.get("content", ""),
                "likes": 0,
                "reposts": 0,
            })
        elif action_type == "LIKE_POST" and self.posts:
            idx = hash(agent_id) % len(self.posts)
            self.posts[idx]["likes"] += 1
        elif action_type == "REPOST" and self.posts:
            idx = hash(agent_id) % len(self.posts)
            self.posts[idx]["reposts"] += 1
        elif action_type == "FOLLOW":
            self.follows.append({"follower": agent_id, "target": args.get("target", "")})

    def get_feed_summary(self, limit: int = 5) -> str:
        recent = self.posts[-limit:] if self.posts else []
        lines = []
        for p in recent:
            lines.append(f"@{p['author']}: {p['content'][:100]} [{p['likes']} likes]")
        return "\n".join(lines) if lines else "(empty feed)"


class FastAgentLoop:
    """Async batch agent simulation — 10x faster than OASIS subprocess."""

    def __init__(
        self,
        router,  # LLMRouter instance
        personas: List[AgentPersona],
        max_rounds: int = 10,
        batch_size: int = 50,
    ):
        self.router = router
        self.personas = personas
        self.max_rounds = max_rounds
        self.batch_size = batch_size
        self.platform_state = PlatformState()
        self.all_actions: List[AgentAction] = []

    def _build_prompt(self, persona: AgentPersona, round_num: int) -> str:
        feed = self.platform_state.get_feed_summary()
        stances_str = ", ".join(f"{k}: {v}" for k, v in persona.stances.items())
        return f"""You are {persona.name}, a {persona.role}.
Background: {persona.background}
Personality: {persona.personality}
Stances: {stances_str}

Current feed:
{feed}

Round {round_num}/{self.max_rounds}. Choose ONE action and respond as JSON:
{{"action": "<one of {', '.join(TWITTER_ACTIONS)}>", "content": "<if posting, your message>"}}
Respond with JSON only."""

    def _parse_response(self, text: str, persona: AgentPersona, round_num: int) -> AgentAction:
        try:
            # Try to extract JSON from response
            match = re.search(r'\{[^}]+\}', text)
            if match:
                data = json.loads(match.group())
            else:
                data = {"action": "DO_NOTHING"}
        except (json.JSONDecodeError, Exception):
            data = {"action": "DO_NOTHING"}

        action_type = data.get("action", "DO_NOTHING")
        if action_type not in TWITTER_ACTIONS:
            action_type = "DO_NOTHING"

        return AgentAction(
            round_num=round_num,
            timestamp=datetime.utcnow().isoformat(),
            platform=persona.platform,
            agent_id=persona.agent_id,
            agent_name=persona.name,
            action_type=action_type,
            action_args={k: v for k, v in data.items() if k != "action"},
        )

    async def run_round(self, round_num: int) -> List[AgentAction]:
        """Run one simulation round — all agents decide in parallel batches."""
        actions = []

        # Process in batches
        for i in range(0, len(self.personas), self.batch_size):
            batch = self.personas[i:i + self.batch_size]
            prompts = [self._build_prompt(p, round_num) for p in batch]

            # Call LLM for each agent (sequentially for now, async later)
            responses = []
            for prompt in prompts:
                try:
                    resp = self.router.chat(
                        task_type="agent_decision",
                        messages=[{"role": "user", "content": prompt}],
                    )
                    responses.append(resp)
                except Exception as e:
                    logger.warning("Agent call failed: %s", e)
                    responses.append('{"action": "DO_NOTHING"}')

            # Parse responses
            for persona, resp in zip(batch, responses):
                action = self._parse_response(resp, persona, round_num)
                self.platform_state.apply_action(
                    action.agent_id, action.agent_name,
                    action.action_type, action.action_args,
                )
                actions.append(action)

        self.all_actions.extend(actions)
        logger.info("Round %d: %d actions", round_num, len(actions))
        return actions

    async def run(self, on_round_complete=None) -> List[AgentAction]:
        """Run full simulation."""
        for round_num in range(1, self.max_rounds + 1):
            actions = await self.run_round(round_num)
            if on_round_complete:
                on_round_complete(round_num, actions)
        return self.all_actions
```

**Step 4: Run tests**

Run: `cd MIROFISH/backend && python -m pytest tests/test_fast_agent_loop.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add backend/app/services/fast_agent_loop.py backend/tests/test_fast_agent_loop.py
git commit -m "feat: add FastLoop agent engine with batch LLM calls"
```

---

## Task 9: Download BGE-M3 Model

**Step 1: Download the model (one-time, ~1.7GB)**

Run:
```bash
cd MIROFISH/backend && python -c "
from sentence_transformers import SentenceTransformer
print('Downloading BGE-M3 (1.7GB)...')
model = SentenceTransformer('BAAI/bge-m3')
print(f'Done. Dimension: {model.get_sentence_embedding_dimension()}')
"
```

Expected: Model downloads to `~/.cache/huggingface/` — dimension 1024.

**Step 2: Download reranker model (~800MB)**

Run:
```bash
cd MIROFISH/backend && python -c "
from sentence_transformers import CrossEncoder
print('Downloading BGE-Reranker-v2-M3...')
model = CrossEncoder('BAAI/bge-reranker-v2-m3')
print('Done.')
"
```

**Step 3: Verify both load**

Run:
```bash
cd MIROFISH/backend && python -c "
from sentence_transformers import SentenceTransformer, CrossEncoder
m = SentenceTransformer('BAAI/bge-m3')
r = CrossEncoder('BAAI/bge-reranker-v2-m3')
emb = m.encode('בדיקת עברית')
score = r.predict([('query', 'document')])
print(f'Embedding dim: {len(emb)}, Reranker score: {score}')
"
```

Expected: `Embedding dim: 1024, Reranker score: <some float>`

---

## Task 10: Add PyYAML Dependency

**Files:**
- Modify: `backend/requirements.txt` — add `pyyaml`

**Step 1: Add dependency**

Add line: `pyyaml>=6.0`

Also add `pytest-asyncio>=0.23` for async tests.

**Step 2: Install**

Run: `cd MIROFISH/backend && pip install pyyaml pytest-asyncio`

**Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add pyyaml and pytest-asyncio dependencies"
```

---

## Task 11: Integration Test — Full Router Flow

**Files:**
- Create: `backend/tests/test_router_integration.py`

**Step 1: Write integration test (mocked LLM calls)**

```python
# backend/tests/test_router_integration.py
"""Integration test: router → provider → cost tracking."""
import os
import pytest
from unittest.mock import patch, MagicMock
from app.resources.llm.provider import LLMProvider
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
    # Mock the client
    mock_client = MagicMock()
    mock_client.chat.return_value = "test response"
    mock_client.model = "llama"
    router._clients["test_groq"] = mock_client

    result = router.chat("agent_decision", [{"role": "user", "content": "test"}])
    assert result == "test response"

    summary = router.cost_tracker.summary()
    assert summary["total_calls"] == 1
    assert "test_groq" in summary["providers"]
```

**Step 2: Run test**

Run: `cd MIROFISH/backend && python -m pytest tests/test_router_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/tests/test_router_integration.py
git commit -m "test: add router integration test with cost tracking"
```

---

## Task 12: Cost Summary API Endpoint

**Files:**
- Modify: `backend/app/api/simulation.py` — add `/simulation/<id>/cost` endpoint

**Step 1: Add endpoint**

Add to the simulation blueprint:

```python
@simulation_bp.route("/simulation/<simulation_id>/cost", methods=["GET"])
def get_simulation_cost(simulation_id):
    """Get LLM cost breakdown for a simulation."""
    # Access the router's cost tracker if available
    from ..resources.llm.provider import LLMProvider
    provider = LLMProvider()
    if provider.is_routed and provider.router:
        return jsonify(provider.router.cost_tracker.summary())
    return jsonify({"message": "Cost tracking requires multi-LLM router", "total_calls": 0})
```

**Step 2: Commit**

```bash
git add backend/app/api/simulation.py
git commit -m "feat: add /simulation/<id>/cost API endpoint"
```

---

## Summary — Execution Order

| Task | Description | Est. Time |
|------|-------------|-----------|
| 1 | Router config YAML | 2 min |
| 10 | Add PyYAML dependency | 2 min |
| 2 | Cost tracker + tests | 5 min |
| 3 | LLM Router core + tests | 10 min |
| 4 | Config + .env updates | 3 min |
| 5 | Wire router into LLMProvider | 5 min |
| 6 | Add task_type to service callers | 10 min |
| 7 | Enable reranking in hybrid search | 5 min |
| 8 | FastLoop agent engine + tests | 10 min |
| 9 | Download BGE-M3 + reranker models | 5 min (+ download time) |
| 11 | Integration test | 5 min |
| 12 | Cost API endpoint | 3 min |
| **Total** | | **~65 min** |
