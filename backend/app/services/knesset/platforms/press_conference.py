"""PressConferencePlatform — press conference simulation mode.

Simulates a Knesset press conference where MKs face journalists in a
structured Q&A format. Journalists ask questions, follow up, and
challenge; MKs answer, deflect, or decline to comment.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..types import KnessetPersona
from .base_platform import BasePlatform, PlatformAction

logger = logging.getLogger("mirofish.knesset.platforms.press_conference")

_MAX_FOLLOW_UPS = 2


class PressConferencePlatform(BasePlatform):
    """Press conference platform for Knesset simulation.

    Models a press conference where MKs stand at a podium and journalists
    ask questions.  Journalists can ASK, FOLLOW_UP (max 2), or CHALLENGE.
    MKs can ANSWER, DEFLECT, or issue NO_COMMENT.
    """

    PLATFORM_ID: str = "press_conference"
    ACTIONS: List[str] = [
        "ASK", "ANSWER", "FOLLOW_UP", "DEFLECT", "NO_COMMENT", "CHALLENGE",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.platform_state: Dict[str, Any] = {
            "podium_queue": [],
            "current_speaker_id": None,
            "qa_log": [],
            "follow_ups": {},
            "deflection_count": {},
            "journalist_ids": set(),
            "mk_ids": set(),
            "_classified": False,
        }

    # ------------------------------------------------------------------
    # Properties for cleaner access
    # ------------------------------------------------------------------

    @property
    def _podium_queue(self) -> List[str]:
        return self.platform_state["podium_queue"]

    @property
    def _current_speaker_id(self) -> Optional[str]:
        return self.platform_state["current_speaker_id"]

    @_current_speaker_id.setter
    def _current_speaker_id(self, value: Optional[str]) -> None:
        self.platform_state["current_speaker_id"] = value

    @property
    def _qa_log(self) -> List[Dict[str, Any]]:
        return self.platform_state["qa_log"]

    @property
    def _follow_ups(self) -> Dict[str, int]:
        return self.platform_state["follow_ups"]

    @property
    def _deflection_count(self) -> Dict[str, int]:
        return self.platform_state["deflection_count"]

    @property
    def _journalist_ids(self) -> set:
        return self.platform_state["journalist_ids"]

    @property
    def _mk_ids(self) -> set:
        return self.platform_state["mk_ids"]

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    def _classify_personas(self, personas: List[KnessetPersona]) -> None:
        """Split personas into journalist and MK sets on first call.

        Heuristic: sort by influence ascending, first 1/3 are journalists.
        """
        if self.platform_state["_classified"]:
            return

        sorted_personas = sorted(personas, key=lambda p: p.influence_score)
        journalist_count = max(1, len(sorted_personas) // 3)

        for i, persona in enumerate(sorted_personas):
            if i < journalist_count:
                self._journalist_ids.add(persona.agent_id)
            else:
                self._mk_ids.add(persona.agent_id)

        self.platform_state["_classified"] = True
        logger.info(
            "Classified %d journalists, %d MKs",
            len(self._journalist_ids), len(self._mk_ids),
        )

    def _ensure_podium(self, persona: KnessetPersona) -> None:
        """Ensure the podium queue is populated and a speaker is set."""
        if persona.agent_id in self._mk_ids:
            if persona.agent_id not in self._podium_queue:
                self._podium_queue.append(persona.agent_id)
        if self._current_speaker_id is None and self._podium_queue:
            self._current_speaker_id = self._podium_queue[0]

    def _is_journalist(self, agent_id: str) -> bool:
        return agent_id in self._journalist_ids

    def _get_current_speaker_name(self) -> str:
        """Find name of current speaker from qa_log or return id."""
        sid = self._current_speaker_id
        if not sid:
            return "(אין)"
        for entry in reversed(self._qa_log):
            if entry.get("answerer_id") == sid:
                return entry.get("answerer_name", sid)
        return sid

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
        """Build a Hebrew press-conference prompt for one participant."""
        # Lazy classification: collect all personas the first time we can
        if not self.platform_state["_classified"]:
            # We only have one persona at a time; register and defer full
            # classification until we have enough data.  Use influence
            # heuristic inline.
            if persona.influence_score < 30 and "עיתונאי" in (persona.personality or ""):
                self._journalist_ids.add(persona.agent_id)
            elif persona.faction or persona.committee_roles:
                self._mk_ids.add(persona.agent_id)
            else:
                # Default: low-influence without faction → journalist
                if persona.influence_score < 30:
                    self._journalist_ids.add(persona.agent_id)
                else:
                    self._mk_ids.add(persona.agent_id)

        self._ensure_podium(persona)

        if self._is_journalist(persona.agent_id):
            return self._build_journalist_prompt(
                persona, round_num, max_rounds, injected_text,
            )
        return self._build_mk_prompt(
            persona, round_num, max_rounds, memory_context, injected_text,
        )

    def _build_journalist_prompt(
        self,
        persona: KnessetPersona,
        round_num: int,
        max_rounds: int,
        injected_text: str,
    ) -> str:
        """Build prompt for a journalist participant."""
        speaker_name = self._get_current_speaker_name()
        speaker_faction = ""
        for entry in reversed(self._qa_log):
            if entry.get("answerer_id") == self._current_speaker_id:
                speaker_faction = entry.get("faction", "")
                break

        # Recent QA entries
        recent = self._qa_log[-5:]
        qa_lines = self._format_qa_lines(recent) if recent else "(טרם נשאלו שאלות)"

        injected_block = f"\n{injected_text}\n" if injected_text else ""
        follow_up_remaining = _MAX_FOLLOW_UPS - self._follow_ups.get(persona.agent_id, 0)

        prompt = (
            f"אתה {persona.name_he}, עיתונאי/ת במסיבת עיתונאים בכנסת.\n"
            f"{persona.personality or ''}\n\n"
            f"על הפודיום: {speaker_name} ({speaker_faction})\n"
            f"דיון עד כה:\n{qa_lines}\n"
            f"{injected_block}\n"
            f"--- סבב {round_num} מתוך {max_rounds} ---\n\n"
            f"בחר פעולה:\n"
            f"- ASK \u2014 שאל שאלה\n"
            f"- FOLLOW_UP \u2014 שאלת המשך (נותרו {follow_up_remaining})\n"
            f"- CHALLENGE \u2014 אתגר תשובה קודמת\n\n"
            f'החזר JSON: {{"action": "...", "question": "...", '
            f'"target_mk_id": "...", "reasoning": "..."}}'
        )
        return prompt

    def _build_mk_prompt(
        self,
        persona: KnessetPersona,
        round_num: int,
        max_rounds: int,
        memory_context: str,
        injected_text: str,
    ) -> str:
        """Build prompt for an MK at the podium."""
        coalition_status = "קואליציה" if persona.coalition_member else "אופוזיציה"

        stances_text = ""
        if persona.stances:
            stances_lines = [f"  - {k}: {v}" for k, v in persona.stances.items()]
            stances_text = "\n".join(stances_lines)

        memory_block = f"\nזיכרון:\n{memory_context}\n" if memory_context else ""

        # Pending questions directed at this MK
        pending = [
            entry for entry in self._qa_log
            if entry.get("answerer_id") is None
            and entry.get("target_mk_id") == persona.agent_id
        ]
        if not pending:
            # Also show questions targeted at "any" or at the current speaker
            pending = [
                entry for entry in self._qa_log
                if entry.get("answerer_id") is None
                and not entry.get("target_mk_id")
            ]

        if pending:
            q_lines = []
            for i, q in enumerate(pending):
                q_lines.append(
                    f"  [{i + 1}] {q.get('questioner_name', '?')}: "
                    f"{q.get('question', '')}"
                )
            pending_text = "\n".join(q_lines)
        else:
            pending_text = "(אין שאלות ממתינות)"

        injected_block = f"\n{injected_text}\n" if injected_text else ""

        prompt = (
            f"אתה {persona.name_he}, חבר כנסת מסיעת {persona.faction}, "
            f"עומד/ת בפני עיתונאים.\n"
            f"{coalition_status} | {stances_text}\n"
            f"{memory_block}\n"
            f"שאלות שנשאלו:\n{pending_text}\n"
            f"{injected_block}\n"
            f"--- סבב {round_num} מתוך {max_rounds} ---\n\n"
            f"בחר פעולה:\n"
            f"- ANSWER \u2014 ענה על שאלה\n"
            f"- DEFLECT \u2014 התחמק מהשאלה\n"
            f"- NO_COMMENT \u2014 \"אין תגובה\"\n\n"
            f'החזר JSON: {{"action": "...", "answer": "...", '
            f'"target_question_id": "...", "reasoning": "..."}}'
        )
        return prompt

    def parse_action(
        self,
        raw_response: str,
        persona: KnessetPersona,
        round_num: int,
    ) -> PlatformAction:
        """Parse LLM response into a PlatformAction."""
        data = self._extract_json(raw_response)
        action_type = self._validate_action_type(data.get("action", "NO_COMMENT"))

        is_journalist = self._is_journalist(persona.agent_id)

        # Enforce role constraints
        journalist_actions = {"ASK", "FOLLOW_UP", "CHALLENGE"}
        mk_actions = {"ANSWER", "DEFLECT", "NO_COMMENT"}

        if is_journalist and action_type not in journalist_actions:
            logger.info(
                "Journalist %s tried MK action '%s', defaulting to ASK",
                persona.agent_id, action_type,
            )
            action_type = "ASK"
        elif not is_journalist and action_type not in mk_actions:
            logger.info(
                "MK %s tried journalist action '%s', defaulting to NO_COMMENT",
                persona.agent_id, action_type,
            )
            action_type = "NO_COMMENT"

        # Enforce follow-up limit
        if action_type == "FOLLOW_UP":
            used = self._follow_ups.get(persona.agent_id, 0)
            if used >= _MAX_FOLLOW_UPS:
                logger.info(
                    "Journalist %s exceeded follow-up limit (%d), "
                    "downgrading to ASK",
                    persona.agent_id, used,
                )
                action_type = "ASK"

        return PlatformAction(
            action_type=action_type,
            raw_data={
                "question": data.get("question", ""),
                "answer": data.get("answer", ""),
                "target_mk_id": data.get("target_mk_id", ""),
                "target_question_id": data.get("target_question_id", ""),
                "reasoning": data.get("reasoning", ""),
                "speech": data.get("answer", data.get("question", "")),
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
        """Apply a parsed action to platform state."""
        action_type = action.action_type
        data = action.raw_data

        if action_type in ("ASK", "FOLLOW_UP", "CHALLENGE"):
            entry: Dict[str, Any] = {
                "questioner_id": mk_id,
                "questioner_name": mk_name,
                "question": data.get("question", ""),
                "answerer_id": None,
                "answerer_name": None,
                "answer": None,
                "round_num": round_num,
                "action_type": action_type,
                "target_mk_id": data.get("target_mk_id", self._current_speaker_id),
            }
            self._qa_log.append(entry)

            if action_type == "FOLLOW_UP":
                self._follow_ups[mk_id] = self._follow_ups.get(mk_id, 0) + 1

        elif action_type == "ANSWER":
            # Link answer to a pending question
            target_qid = data.get("target_question_id", "")
            linked = self._link_answer(mk_id, mk_name, data.get("answer", ""), target_qid, round_num)
            if not linked:
                # Append as standalone answer
                self._qa_log.append({
                    "questioner_id": None,
                    "questioner_name": None,
                    "question": None,
                    "answerer_id": mk_id,
                    "answerer_name": mk_name,
                    "answer": data.get("answer", ""),
                    "round_num": round_num,
                    "action_type": "ANSWER",
                })
            if hasattr(parliament_state, "record_speech"):
                parliament_state.record_speech(
                    mk_id, mk_name, data.get("answer", ""), round_num,
                )

        elif action_type == "DEFLECT":
            self._link_answer(mk_id, mk_name, "(התחמקות)", "", round_num)
            self._deflection_count[mk_id] = self._deflection_count.get(mk_id, 0) + 1
            self._qa_log.append({
                "questioner_id": None,
                "questioner_name": None,
                "question": None,
                "answerer_id": mk_id,
                "answerer_name": mk_name,
                "answer": data.get("answer", "(התחמקות)"),
                "round_num": round_num,
                "action_type": "DEFLECT",
            })

        elif action_type == "NO_COMMENT":
            self._qa_log.append({
                "questioner_id": None,
                "questioner_name": None,
                "question": None,
                "answerer_id": mk_id,
                "answerer_name": mk_name,
                "answer": "אין תגובה",
                "round_num": round_num,
                "action_type": "NO_COMMENT",
            })

        else:
            logger.warning(
                "Unhandled action type '%s' for %s in press_conference",
                action_type, mk_id,
            )

    def get_state_summary(self, persona_id: str) -> str:
        """Return a Hebrew summary of the current press conference state."""
        total_questions = sum(
            1 for e in self._qa_log if e.get("question") is not None
        )
        total_deflections = sum(self._deflection_count.values())
        return (
            f"מסיבת עיתונאים: {total_questions} שאלות, "
            f"{total_deflections} התחמקויות"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_qa_lines(self, entries: List[Dict[str, Any]]) -> str:
        """Format QA log entries into readable Hebrew lines."""
        lines = []
        for entry in entries:
            if entry.get("question"):
                prefix = f"[{entry['action_type']}] {entry.get('questioner_name', '?')}"
                lines.append(f"{prefix}: {entry['question']}")
            if entry.get("answer"):
                prefix = f"[{entry['action_type']}] {entry.get('answerer_name', '?')}"
                lines.append(f"{prefix}: {entry['answer']}")
        return "\n".join(lines) if lines else "(אין)"

    def _link_answer(
        self,
        mk_id: str,
        mk_name: str,
        answer: str,
        target_qid: str,
        round_num: int,
    ) -> bool:
        """Link an answer to the first unanswered question directed at mk_id.

        Returns True if a question was found and linked, False otherwise.
        """
        # Try to match by target_question_id (1-based index)
        target_idx: Optional[int] = None
        if target_qid:
            cleaned = target_qid.strip().lstrip("#")
            try:
                target_idx = int(cleaned) - 1
            except ValueError:
                target_idx = None

        for i, entry in enumerate(self._qa_log):
            if entry.get("answerer_id") is not None:
                continue
            if entry.get("question") is None:
                continue
            # Match by explicit index or by target_mk_id
            if target_idx is not None and i != target_idx:
                continue
            if target_idx is None:
                t = entry.get("target_mk_id")
                if t and t != mk_id:
                    continue

            entry["answerer_id"] = mk_id
            entry["answerer_name"] = mk_name
            entry["answer"] = answer
            return True

        return False
