"""Helpers for using CLI-backed LLMs inside OASIS/CAMEL simulations."""

import asyncio
import json
import math
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from camel.models.openai_model import OpenAIModel
from openai.types.chat.chat_completion import ChatCompletion

from ..config import Config
from .llm_client import LLMClient
from .logger import get_logger

logger = get_logger('mirofish.oasis_llm')

DEFAULT_CLI_SEMAPHORE = 3

# CLI providers return plain text, so tool calling is implemented at the
# prompt level: tool schemas are serialized into the prompt and the model is
# asked to answer with a single JSON object that either carries tool_calls or
# plain content. The response is parsed back into an OpenAI-shaped
# ChatCompletion so CAMEL's ChatAgent executes the tools exactly as it would
# with a native function-calling backend. Without this, OASIS agents can
# never act on the platform (their actions ARE tool calls) and simulation
# rounds silently stay empty.
_TOOL_PROMPT_HEADER = (
    "You can act ONLY by calling the tools listed below.\n"
    "AVAILABLE TOOLS (name | description | JSON parameters schema):\n"
)

_TOOL_PROMPT_FOOTER = (
    "\nRESPONSE FORMAT - respond with a single JSON object and nothing else:\n"
    '- To act: {"tool_calls": [{"name": "<tool_name>", "arguments": {<parameters>}}]}\n'
    "  You may include several tool calls in the list, in execution order.\n"
    '- To answer in plain text with no action: {"content": "<your text>"}\n'
    "Do not wrap the JSON in markdown fences. Only use tool names from the list above.\n"
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _serialize_tools(tools: List[Dict[str, Any]]) -> str:
    lines = []
    for tool in tools or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        name = fn.get("name", "?")
        desc = (fn.get("description") or "").strip().replace("\n", " ")[:200]
        params = json.dumps(fn.get("parameters", {}), ensure_ascii=False)
        lines.append(f"- {name} | {desc} | parameters: {params}")
    return "\n".join(lines)


def _normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten tool-protocol messages into plain text the CLI can consume."""
    norm: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if role == "tool":
            label = msg.get("name") or msg.get("tool_call_id") or "tool"
            norm.append({"role": "user", "content": f"TOOL RESULT [{label}]: {content}"})
            continue
        if content is None:
            calls = msg.get("tool_calls") or []
            if calls:
                summary = "; ".join(
                    f"{(c.get('function') or {}).get('name', '?')}"
                    f"({(c.get('function') or {}).get('arguments', '')})"
                    for c in calls if isinstance(c, dict)
                )
                norm.append({"role": role, "content": f"[previously called tools: {summary}]"})
            continue
        norm.append({"role": role, "content": content})
    return norm


def _parse_cli_tool_response(text: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Extract (tool_calls, content) from the CLI's raw text response.

    Returns (calls, None) when valid tool calls were found, otherwise
    (None, content) with the best plain-text interpretation.
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    candidate = None
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(raw)
        if match:
            try:
                candidate = json.loads(match.group(0))
            except json.JSONDecodeError:
                candidate = None

    if isinstance(candidate, dict):
        calls = candidate.get("tool_calls")
        if isinstance(calls, list) and calls:
            valid = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                name = call.get("name") or fn.get("name")
                args = call.get("arguments", fn.get("arguments", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                if name:
                    valid.append({
                        "name": str(name),
                        "arguments": args if isinstance(args, dict) else {},
                    })
            if valid:
                return valid, None
        if isinstance(candidate.get("content"), str):
            return None, candidate["content"]

    return None, text


class CLIModel(OpenAIModel):
    """CAMEL model backend that proxies requests to Claude/Codex CLI."""

    def __init__(
        self,
        model_type: str,
        provider: str,
        model_config_dict: Dict[str, Any] | None = None,
        api_key: str | None = None,
        url: str | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self.provider = (provider or '').lower()
        self._llm = LLMClient(provider=self.provider)
        super().__init__(
            model_type=model_type,
            model_config_dict=model_config_dict,
            api_key=api_key or 'cli-bridge',
            url=url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _estimate_tokens(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return max(1, math.ceil(len(value) / 4)) if value else 0
        if isinstance(value, list):
            return sum(self._estimate_tokens(item) for item in value)
        if isinstance(value, dict):
            return self._estimate_tokens(json.dumps(value, ensure_ascii=False))
        return self._estimate_tokens(str(value))

    def _build_completion(
        self,
        messages: List[Dict[str, Any]],
        content: Optional[str],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatCompletion:
        prompt_tokens = sum(self._estimate_tokens(message.get('content')) for message in messages)
        completion_tokens = self._estimate_tokens(content if content is not None else tool_calls)

        message: Dict[str, Any] = {'role': 'assistant', 'content': content}
        finish_reason = 'stop'
        if tool_calls:
            message['content'] = None
            message['tool_calls'] = [
                {
                    'id': f'call_{uuid.uuid4().hex[:20]}',
                    'type': 'function',
                    'function': {
                        'name': call['name'],
                        'arguments': json.dumps(call['arguments'], ensure_ascii=False),
                    },
                }
                for call in tool_calls
            ]
            finish_reason = 'tool_calls'

        return ChatCompletion.model_validate(
            {
                'id': f'chatcmpl-cli-{uuid.uuid4().hex[:24]}',
                'object': 'chat.completion',
                'created': int(time.time()),
                'model': self.provider,
                'choices': [
                    {
                        'index': 0,
                        'message': message,
                        'finish_reason': finish_reason,
                    }
                ],
                'usage': {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': prompt_tokens + completion_tokens,
                },
            }
        )

    def _request_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        temperature = float((self.model_config_dict or {}).get('temperature', 0.7) or 0.7)
        max_tokens = int((self.model_config_dict or {}).get('max_tokens', 4096) or 4096)

        norm_messages = _normalize_messages(messages)
        if tools:
            instruction = _TOOL_PROMPT_HEADER + _serialize_tools(tools) + _TOOL_PROMPT_FOOTER
            norm_messages = norm_messages + [{"role": "user", "content": instruction}]

        content = self._llm.chat(
            messages=norm_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if tools:
            calls, text = _parse_cli_tool_response(content)
            if calls:
                logger.info(
                    f"CLI tool-calling: parsed {len(calls)} tool call(s): "
                    f"{[call['name'] for call in calls]}"
                )
                return self._build_completion(norm_messages, None, tool_calls=calls)
            logger.info("CLI tool-calling: response carried no tool call; returning plain content")
            return self._build_completion(norm_messages, text)

        return self._build_completion(norm_messages, content)

    async def _arequest_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_chat_completion, messages, tools)

    def _request_parse(
        self,
        messages: List[Dict[str, Any]],
        response_format,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        if tools:
            logger.warning('CLIModel ignores tool schemas during structured output requests')

        temperature = float((self.model_config_dict or {}).get('temperature', 0.3) or 0.3)
        max_tokens = int((self.model_config_dict or {}).get('max_tokens', 4096) or 4096)
        payload = self._llm.chat_json(
            messages=_normalize_messages(messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._build_completion(messages, json.dumps(payload, ensure_ascii=False))

    async def _arequest_parse(
        self,
        messages: List[Dict[str, Any]],
        response_format,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_parse, messages, response_format, tools)


def create_oasis_model(config: Dict[str, Any], use_boost: bool = False):
    """Create the CAMEL model used by OASIS simulations."""
    provider = (
        os.environ.get('LLM_PROVIDER')
        or config.get('llm_provider')
        or Config.LLM_PROVIDER
        or 'claude-cli'
    ).lower()

    model = config.get('llm_model') or provider

    logger.info(f"OASIS model: provider={provider}, model={model}, mode=cli-bridge (prompt-level tool calling)")
    return CLIModel(
        model_type=model,
        provider=provider,
        model_config_dict={},
        api_key='cli-bridge',
    )


def get_oasis_semaphore(config: Dict[str, Any], use_boost: bool = False) -> int:
    """Get CLI-appropriate OASIS concurrency limit."""
    return int(os.environ.get('OASIS_CLI_SEMAPHORE', str(DEFAULT_CLI_SEMAPHORE)))
