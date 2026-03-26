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

        self._routes = raw.get("routing", {})
        logger.info(
            "Loaded router config: %d providers, %d routes",
            len(self.providers), len(self._routes),
        )

    def resolve(self, task_type: str) -> RouteConfig:
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
        if provider_name in self._clients:
            return self._clients[provider_name]

        prov = self.providers.get(provider_name)
        if not prov:
            raise ValueError(f"Unknown provider: {provider_name}")

        from ...utils.llm_client import LLMClient

        if prov.type == "anthropic":
            client = LLMClient(api_key=prov.api_key, provider="anthropic")
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

    def chat(self, task_type: str, messages: list[dict],
             temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
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
                input_text = " ".join(m.get("content", "") for m in messages)
                input_tokens = len(input_text) // 4
                output_tokens = len(result) // 4
                self.cost_tracker.record(prov_name, model, input_tokens, output_tokens)
                return result
            except Exception as e:
                last_error = e
                logger.warning("Provider %s failed for task %s: %s", prov_name, task_type, e)

        raise RuntimeError(f"All providers failed for task '{task_type}': {last_error}")

    def chat_json(self, task_type: str, messages: list[dict],
                  temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> dict:
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
                output_tokens = 500
                self.cost_tracker.record(prov_name, model, input_tokens, output_tokens)
                return result
            except Exception as e:
                last_error = e
                logger.warning("Provider %s JSON failed for task %s: %s", prov_name, task_type, e)

        raise RuntimeError(f"All providers failed for JSON task '{task_type}': {last_error}")
