"""BrainstormPlatform — two-phase brainstorming interaction mode.

Divergent phase (early rounds): encourages IDEA, BUILD_ON, COMBINE.
Convergent phase (later rounds): encourages CRITIQUE, PRIORITIZE, VOTE.
All prompts and state labels are in Hebrew.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from ..types import KnessetPersona
from .base_platform import BasePlatform, PlatformAction

logger = logging.getLogger("mirofish.knesset.platforms.brainstorm")

_DEFAULT_DIVERGENT_CUTOFF = 3


class BrainstormPlatform(BasePlatform):
    """Knesset brainstorming platform with divergent/convergent phases.

    Ideas are proposed, extended, critiqued, combined, prioritised
    and voted on across two phases driven by round number.
    """

    PLATFORM_ID: str = "brainstorm"
    ACTIONS: List[str] = [
        "IDEA",
        "BUILD_ON",
        "CRITIQUE",
        "COMBINE",
        "PRIORITIZE",
        "VOTE",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.platform_state: Dict[str, Any] = {
            "ideas": [],
            "build_chains": {},
            "critiques": [],
            "combined_ideas": [],
            "priority_votes": {},
            "phase": "divergent",
            "divergent_cutoff": _DEFAULT_DIVERGENT_CUTOFF,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_phase(self, round_num: int) -> str:
        cutoff = self.platform_state.get("divergent_cutoff", _DEFAULT_DIVERGENT_CUTOFF)
        return "divergent" if round_num <= cutoff else "convergent"

    def _format_ideas_block(self) -> str:
        ideas: List[Dict[str, Any]] = self.platform_state.get("ideas", [])
        if not ideas:
            return "אין רעיונות עדיין."

        lines: List[str] = []
        build_chains: Dict[str, List[Dict[str, Any]]] = self.platform_state.get("build_chains", {})

        for idea in ideas:
            iid = idea["idea_id"]
            votes = idea.get("votes", 0)
            line = f"💡 [{votes} הצבעות] ({iid}) {idea['content_he']}"
            lines.append(line)

            chain = build_chains.get(iid, [])
            for ext in chain:
                lines.append(f"   ↳ {ext['agent_name']}: {ext['addition_he']}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # build_prompt
    # ------------------------------------------------------------------

    def build_prompt(
        self,
        persona: KnessetPersona,
        round_num: int,
        max_rounds: int,
        parliament_summary: str,
        memory_context: str,
        injected_text: str,
    ) -> str:
        phase = self._current_phase(round_num)
        self.platform_state["phase"] = phase

        phase_name = "התרחבות" if phase == "divergent" else "התכנסות"

        if phase == "divergent":
            phase_instruction = "עדיין בשלב הרעיונות — מומלץ להציע ולבנות."
        else:
            phase_instruction = "שלב הסינון — מומלץ לבחון ולהצביע."

        stances_lines = "\n".join(
            f"- {topic}: {stance}" for topic, stance in persona.stances.items()
        )

        memory_block = f"\n--- זיכרון ---\n{memory_context}\n" if memory_context else ""
        injected_block = f"\n--- הזרקת אירוע ---\n{injected_text}\n" if injected_text else ""

        ideas_block = self._format_ideas_block()

        return (
            f"אתה {persona.name_he}, משתתף בסיעור מוחות בכנסת.\n"
            f"סיעת {persona.faction}\n\n"
            f"עמדות:\n{stances_lines}\n"
            f"{memory_block}"
            f"\n--- שלב: {phase_name} ({round_num}/{max_rounds}) ---\n\n"
            f"רעיונות על השולחן:\n{ideas_block}\n"
            f"{injected_block}\n"
            f"{phase_instruction}\n\n"
            "בחר פעולה:\n"
            "- IDEA — הצע רעיון חדש\n"
            "- BUILD_ON — הרחב רעיון קיים\n"
            "- CRITIQUE — בקר רעיון\n"
            "- COMBINE — שלב שני רעיונות\n"
            "- PRIORITIZE — דרג רעיונות (1-5)\n"
            "- VOTE — הצבע לרעיון מועדף\n\n"
            "השב בפורמט JSON בלבד:\n"
            '{"action": "...", "content": "...", "idea_id": "...", '
            '"source_ideas": [...], "score": 3, "reasoning": "..."}'
        )

    # ------------------------------------------------------------------
    # parse_action
    # ------------------------------------------------------------------

    def parse_action(
        self,
        raw_response: str,
        persona: KnessetPersona,
        round_num: int,
    ) -> PlatformAction:
        data = self._extract_json(raw_response)

        if not data:
            logger.warning(
                "Could not parse JSON from %s (round %d), falling back to IDEA",
                persona.name_he, round_num,
            )
            return PlatformAction(
                action_type="IDEA",
                raw_data={"content": raw_response[:200], "reasoning": "fallback"},
            )

        raw_action = data.get("action", "IDEA")
        validated = self._validate_action_type(raw_action)
        return PlatformAction(action_type=validated, raw_data=data)

    # ------------------------------------------------------------------
    # apply_action
    # ------------------------------------------------------------------

    def apply_action(
        self,
        parliament_state: Any,
        mk_id: str,
        mk_name: str,
        action: PlatformAction,
        round_num: int,
    ) -> None:
        ideas: List[Dict[str, Any]] = self.platform_state["ideas"]
        build_chains: Dict[str, List[Dict[str, Any]]] = self.platform_state["build_chains"]
        data = action.raw_data

        if action.action_type == "IDEA":
            idea_id = f"idea-{uuid.uuid4().hex[:8]}"
            ideas.append({
                "idea_id": idea_id,
                "agent_id": mk_id,
                "agent_name": mk_name,
                "content_he": data.get("content", ""),
                "votes": 0,
                "round_num": round_num,
            })
            logger.info("IDEA %s by %s: %s", idea_id, mk_name, data.get("content", "")[:60])

        elif action.action_type == "BUILD_ON":
            idea_id = data.get("idea_id", "")
            if idea_id not in build_chains:
                build_chains[idea_id] = []
            build_chains[idea_id].append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "addition_he": data.get("content", ""),
            })

        elif action.action_type == "CRITIQUE":
            self.platform_state["critiques"].append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "idea_id": data.get("idea_id", ""),
                "critique_he": data.get("content", ""),
            })

        elif action.action_type == "COMBINE":
            source_ideas = data.get("source_ideas", [])
            combined_id = f"combined-{uuid.uuid4().hex[:8]}"
            combined_text = data.get("content", "")

            ideas.append({
                "idea_id": combined_id,
                "agent_id": mk_id,
                "agent_name": mk_name,
                "content_he": combined_text,
                "votes": 0,
                "round_num": round_num,
            })
            self.platform_state["combined_ideas"].append({
                "combined_id": combined_id,
                "source_ideas": source_ideas,
                "combined_text_he": combined_text,
                "agent_id": mk_id,
            })

        elif action.action_type == "PRIORITIZE":
            idea_id = data.get("idea_id", "")
            score = int(data.get("score", 3))
            score = max(1, min(5, score))
            pv: Dict[str, Dict[str, int]] = self.platform_state["priority_votes"]
            if idea_id not in pv:
                pv[idea_id] = {}
            pv[idea_id][mk_id] = score

        elif action.action_type == "VOTE":
            idea_id = data.get("idea_id", "")
            for idea in ideas:
                if idea["idea_id"] == idea_id:
                    idea["votes"] = idea.get("votes", 0) + 1
                    break

    # ------------------------------------------------------------------
    # get_state_summary
    # ------------------------------------------------------------------

    def get_state_summary(self, persona_id: str) -> str:
        ideas = self.platform_state.get("ideas", [])
        phase = self.platform_state.get("phase", "divergent")
        phase_he = "התרחבות" if phase == "divergent" else "התכנסות"
        return f"סיעור מוחות: {len(ideas)} רעיונות, שלב {phase_he}"
