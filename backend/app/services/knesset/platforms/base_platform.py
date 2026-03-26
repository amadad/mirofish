"""BasePlatform — abstract base class for all simulation platforms.

Each platform defines the interaction mode (actions, prompts, state)
that the KnessetLoop engine delegates to during simulation rounds.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..types import KnessetAction, KnessetPersona

logger = logging.getLogger("mirofish.knesset.platforms")


@dataclass
class PlatformAction:
    """Parsed action from an LLM response, platform-agnostic wrapper."""

    action_type: str
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def bill_id(self) -> Optional[str]:
        return self.raw_data.get("bill_id")

    @property
    def vote_value(self) -> Optional[str]:
        return self.raw_data.get("vote")

    @property
    def speech_text(self) -> Optional[str]:
        return self.raw_data.get("speech")

    @property
    def reasoning(self) -> str:
        return self.raw_data.get("reasoning", "")

    @property
    def target_mk_id(self) -> Optional[str]:
        return self.raw_data.get("target_mk_id")


class BasePlatform(ABC):
    """Abstract base for all Knesset simulation interaction modes.

    Subclasses must define PLATFORM_ID, ACTIONS, and implement the four
    core methods: build_prompt, parse_action, apply_action, get_state_summary.
    """

    PLATFORM_ID: str = ""
    ACTIONS: List[str] = []

    def __init__(self) -> None:
        self.platform_state: Dict[str, Any] = {}

    @abstractmethod
    def build_prompt(
        self,
        persona: KnessetPersona,
        round_num: int,
        max_rounds: int,
        parliament_summary: str,
        memory_context: str,
        injected_text: str,
    ) -> str:
        """Build a Hebrew prompt for one MK in this platform's format."""
        ...

    @abstractmethod
    def parse_action(
        self,
        raw_response: str,
        persona: KnessetPersona,
        round_num: int,
    ) -> PlatformAction:
        """Parse LLM text response into a PlatformAction."""
        ...

    @abstractmethod
    def apply_action(
        self,
        parliament_state: Any,
        mk_id: str,
        mk_name: str,
        action: PlatformAction,
        round_num: int,
    ) -> None:
        """Apply a parsed action to parliament state and platform state."""
        ...

    @abstractmethod
    def get_state_summary(self, persona_id: str) -> str:
        """Return a Hebrew summary of platform-specific state for this persona."""
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON object from LLM response text."""
        cleaned = text.strip()

        # Try markdown code fence
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1)
        else:
            # Try bare JSON object
            json_match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group()

        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, Exception):
            return {}

    def _validate_action_type(self, action_type: str) -> str:
        """Validate action type against this platform's allowed actions."""
        action_upper = action_type.upper()
        if action_upper in self.ACTIONS:
            return action_upper
        logger.warning(
            "Invalid action '%s' for platform %s, using fallback",
            action_type, self.PLATFORM_ID,
        )
        # Return last action (typically DO_NOTHING or ABSTAIN)
        return self.ACTIONS[-1] if self.ACTIONS else "DO_NOTHING"

    def to_knesset_action(
        self,
        platform_action: PlatformAction,
        persona: KnessetPersona,
        round_num: int,
    ) -> KnessetAction:
        """Convert a PlatformAction to a KnessetAction for storage."""
        return KnessetAction(
            round_num=round_num,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=persona.agent_id,
            agent_name=persona.name_he,
            action_type=platform_action.action_type,
            bill_id=platform_action.bill_id,
            vote_value=platform_action.vote_value,
            speech_text=platform_action.speech_text,
            reasoning=platform_action.reasoning,
            target_mk_id=platform_action.target_mk_id,
        )
