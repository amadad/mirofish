"""RoundtablePlatform — roundtable discussion simulation mode.

Simulates a structured roundtable discussion among Knesset members,
with turn-based speaking, proposals, and agreement tracking.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..types import KnessetPersona
from .base_platform import BasePlatform, PlatformAction

logger = logging.getLogger("mirofish.knesset.platforms.roundtable")


class RoundtablePlatform(BasePlatform):
    """Roundtable discussion platform for Knesset simulation.

    Models a structured discussion where MKs take turns speaking,
    can propose ideas, respond to others, challenge claims, or agree
    with proposals on the table.
    """

    PLATFORM_ID: str = "roundtable"
    ACTIONS: List[str] = [
        "SPEAK", "RESPOND", "CHALLENGE", "AGREE", "PROPOSE", "ABSTAIN",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.platform_state: Dict[str, Any] = {
            "speaker_queue": [],
            "discussion_log": [],
            "proposals": [],
            "agreements": {},
        }

    # ------------------------------------------------------------------
    # Properties for cleaner access
    # ------------------------------------------------------------------

    @property
    def _speaker_queue(self) -> List[str]:
        return self.platform_state["speaker_queue"]

    @property
    def _discussion_log(self) -> List[Dict[str, Any]]:
        return self.platform_state["discussion_log"]

    @property
    def _proposals(self) -> List[Dict[str, Any]]:
        return self.platform_state["proposals"]

    @property
    def _agreements(self) -> Dict[str, List[str]]:
        return self.platform_state["agreements"]

    # ------------------------------------------------------------------
    # Speaker queue helpers
    # ------------------------------------------------------------------

    def _ensure_speaker_queue(self, persona: KnessetPersona) -> None:
        """Populate speaker queue on first call if empty."""
        if not self._speaker_queue:
            self._speaker_queue.append(persona.agent_id)

    def _register_speaker(self, agent_id: str) -> None:
        """Add an agent to the speaker queue if not already present."""
        if agent_id not in self._speaker_queue:
            self._speaker_queue.append(agent_id)

    def _current_speaker(self, round_num: int) -> str:
        """Return the agent_id of whoever has the floor this round."""
        if not self._speaker_queue:
            return ""
        return self._speaker_queue[(round_num - 1) % len(self._speaker_queue)]

    # ------------------------------------------------------------------
    # Core interface
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
        """Build a Hebrew roundtable prompt for one MK."""
        self._ensure_speaker_queue(persona)
        self._register_speaker(persona.agent_id)

        current = self._current_speaker(round_num)
        is_my_turn = persona.agent_id == current

        coalition_status = "קואליציה" if persona.coalition_member else "אופוזיציה"
        personality_short = persona.personality[:100] if persona.personality else ""

        # Format stances
        stances_text = ""
        if persona.stances:
            stances_lines = [f"  - {k}: {v}" for k, v in persona.stances.items()]
            stances_text = "\n".join(stances_lines)

        # Last 5 discussion entries
        recent = self._discussion_log[-5:]
        discussion_lines = ""
        if recent:
            entries = []
            for entry in recent:
                prefix = f"[{entry['action_type']}] {entry['agent_name']}"
                entries.append(f"{prefix}: {entry['content']}")
            discussion_lines = "\n".join(entries)
        else:
            discussion_lines = "(אין הודעות עדיין)"

        # Proposals list
        proposals_text = ""
        if self._proposals:
            p_lines = []
            for i, prop in enumerate(self._proposals):
                supporter_count = len(prop.get("supporters", []))
                p_lines.append(
                    f"  [{i + 1}] {prop['agent_name']}: {prop['proposal_text']} "
                    f"(תומכים: {supporter_count})"
                )
            proposals_text = "\n".join(p_lines)
        else:
            proposals_text = "(אין הצעות על השולחן)"

        # Turn indicator
        if is_my_turn:
            turn_text = ">>> תורך לדבר! <<<"
        else:
            current_name = current  # fallback to agent_id
            for entry in self._discussion_log:
                if entry["agent_id"] == current:
                    current_name = entry["agent_name"]
                    break
            turn_text = f"לא תורך — הדובר הנוכחי: {current_name}. תוכל להגיב."

        # Injected text block
        injected_block = f"\n{injected_text}\n" if injected_text else ""

        # Memory context block
        memory_block = f"\nזיכרון:\n{memory_context}\n" if memory_context else ""

        prompt = (
            f"אתה {persona.name_he}, משתתף בדיון שולחן עגול בנושא הנדון בכנסת.\n"
            f"מסיעת {persona.faction} | {coalition_status}\n\n"
            f"{personality_short}\n\n"
            f"עמדותיך:\n{stances_text}\n"
            f"{memory_block}\n"
            f"--- מצב הדיון ---\n"
            f"{parliament_summary}\n\n"
            f"{discussion_lines}\n\n"
            f"הצעות על השולחן:\n{proposals_text}\n"
            f"{injected_block}\n"
            f"--- סבב {round_num} מתוך {max_rounds} ---\n"
            f"{turn_text}\n\n"
            f"בחר פעולה:\n"
            f"- SPEAK — דבר (רק בתורך)\n"
            f"- RESPOND — הגב לדובר\n"
            f"- CHALLENGE — אתגר טענה\n"
            f"- AGREE — הסכם עם הצעה\n"
            f"- PROPOSE — הצע הצעה חדשה\n"
            f"- ABSTAIN — שתוק\n\n"
            f'החזר JSON: {{"action": "...", "content": "...", '
            f'"target_proposal": "...", "reasoning": "..."}}'
        )
        return prompt

    def parse_action(
        self,
        raw_response: str,
        persona: KnessetPersona,
        round_num: int,
    ) -> PlatformAction:
        """Parse LLM response into a PlatformAction.

        If the persona is not the current speaker and chose SPEAK,
        downgrade to RESPOND.
        """
        data = self._extract_json(raw_response)

        action_type = self._validate_action_type(
            data.get("action", "ABSTAIN")
        )

        # Enforce turn-based speaking
        current = self._current_speaker(round_num)
        if action_type == "SPEAK" and persona.agent_id != current:
            logger.info(
                "Persona %s tried to SPEAK out of turn (round %d), "
                "downgrading to RESPOND",
                persona.agent_id, round_num,
            )
            action_type = "RESPOND"

        return PlatformAction(
            action_type=action_type,
            raw_data={
                "content": data.get("content", ""),
                "target_proposal": data.get("target_proposal", ""),
                "reasoning": data.get("reasoning", ""),
                "speech": data.get("content", ""),
            },
        )

    def apply_action(
        self,
        parliament_state: Any,
        mk_id: str,
        mk_name: str,
        action: PlatformAction,
        round_num: int,
    ) -> None:
        """Apply a parsed action to platform state and parliament state."""
        content = action.raw_data.get("content", "")
        action_type = action.action_type

        if action_type in ("SPEAK", "RESPOND", "CHALLENGE"):
            self._discussion_log.append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "action_type": action_type,
                "content": content,
                "round_num": round_num,
            })
            # Record speech in parliament state for report generation
            if action_type == "SPEAK" and hasattr(parliament_state, "record_speech"):
                parliament_state.record_speech(mk_id, mk_name, content, round_num)

        elif action_type == "PROPOSE":
            proposal_id = f"prop-{len(self._proposals) + 1}"
            self._proposals.append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "proposal_text": content,
                "supporters": [mk_id],
            })
            self._agreements[proposal_id] = [mk_id]
            self._discussion_log.append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "action_type": "PROPOSE",
                "content": content,
                "round_num": round_num,
            })

        elif action_type == "AGREE":
            target = action.raw_data.get("target_proposal", "")
            self._add_agreement(mk_id, target)
            self._discussion_log.append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "action_type": "AGREE",
                "content": content or f"(מסכים עם הצעה {target})",
                "round_num": round_num,
            })

        elif action_type == "ABSTAIN":
            self._discussion_log.append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "action_type": "ABSTAIN",
                "content": "(נמנע)",
                "round_num": round_num,
            })

        else:
            logger.warning(
                "Unhandled action type '%s' for %s in roundtable",
                action_type, mk_id,
            )

    def get_state_summary(self, persona_id: str) -> str:
        """Return a Hebrew summary of the current roundtable state."""
        return (
            f"דיון: {len(self._discussion_log)} הודעות, "
            f"{len(self._proposals)} הצעות"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_agreement(self, mk_id: str, target: str) -> None:
        """Add mk_id as a supporter for the target proposal."""
        # Try to match by index (1-based) or proposal id
        proposal_idx = self._resolve_proposal_index(target)
        if proposal_idx is not None and 0 <= proposal_idx < len(self._proposals):
            proposal = self._proposals[proposal_idx]
            if mk_id not in proposal["supporters"]:
                proposal["supporters"].append(mk_id)
            # Also update agreements dict
            prop_id = f"prop-{proposal_idx + 1}"
            if prop_id not in self._agreements:
                self._agreements[prop_id] = []
            if mk_id not in self._agreements[prop_id]:
                self._agreements[prop_id].append(mk_id)
        else:
            logger.warning(
                "Could not resolve proposal target '%s' for agreement by %s",
                target, mk_id,
            )

    def _resolve_proposal_index(self, target: str) -> int | None:
        """Resolve a proposal target string to a 0-based index."""
        if not target:
            # Default to last proposal if any
            return len(self._proposals) - 1 if self._proposals else None

        # Try numeric (1-based from prompt display)
        cleaned = target.strip().lstrip("#").replace("prop-", "")
        try:
            idx = int(cleaned) - 1
            if 0 <= idx < len(self._proposals):
                return idx
        except ValueError:
            pass

        # Try matching by agent_id or partial text
        for i, prop in enumerate(self._proposals):
            if target in prop.get("agent_id", "") or target in prop.get("proposal_text", ""):
                return i

        return None
