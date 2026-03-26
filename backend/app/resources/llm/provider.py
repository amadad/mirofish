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
