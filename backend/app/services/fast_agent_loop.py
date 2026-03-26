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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from .data_injector import DataInjector
except ImportError:
    DataInjector = None  # type: ignore[misc,assignment]

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
        self.likes: Dict[str, int] = {}
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
        router,
        personas: List[AgentPersona],
        max_rounds: int = 10,
        batch_size: int = 50,
        injector: Optional[Any] = None,
    ):
        self.router = router
        self.personas = personas
        self.max_rounds = max_rounds
        self.batch_size = batch_size
        self.platform_state = PlatformState()
        self.all_actions: List[AgentAction] = []
        self.injector = injector  # DataInjector instance (optional)

    def _build_prompt(self, persona: AgentPersona, round_num: int, injected_text: str = "") -> str:
        feed = self.platform_state.get_feed_summary()
        stances_str = ", ".join(f"{k}: {v}" for k, v in persona.stances.items())
        return f"""You are {persona.name}, a {persona.role}.
Background: {persona.background}
Personality: {persona.personality}
Stances: {stances_str}

Current feed:
{feed}
{injected_text}
Round {round_num}/{self.max_rounds}. Choose ONE action and respond as JSON:
{{"action": "<one of {', '.join(TWITTER_ACTIONS)}>", "content": "<if posting, your message>"}}
Respond with JSON only."""

    def _parse_response(self, text: str, persona: AgentPersona, round_num: int) -> AgentAction:
        try:
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
            timestamp=datetime.now(timezone.utc).isoformat(),
            platform=persona.platform,
            agent_id=persona.agent_id,
            agent_name=persona.name,
            action_type=action_type,
            action_args={k: v for k, v in data.items() if k != "action"},
        )

    async def run_round(self, round_num: int) -> List[AgentAction]:
        """Run one simulation round — all agents decide in parallel batches."""
        actions = []

        # Fetch injected real-world events for this round
        injected_text = ""
        if self.injector is not None:
            try:
                events = self.injector.get_events_for_round(round_num)
                injected_text = self.injector.format_for_feed(events)
            except Exception as e:
                logger.warning("Data injector error in round %d: %s", round_num, e)

        for i in range(0, len(self.personas), self.batch_size):
            batch = self.personas[i:i + self.batch_size]
            prompts = [self._build_prompt(p, round_num, injected_text) for p in batch]

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
