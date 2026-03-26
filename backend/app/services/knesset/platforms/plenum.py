"""PlenumPlatform — Knesset plenum (full assembly) interaction mode.

Extracts the core plenum simulation logic from knesset_loop.py into a
pluggable BasePlatform subclass.  Supports all eight classic Knesset
actions: propose bills, vote, speak, lobby, form alliances, amend bills,
defect, or do nothing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..types import KNESSET_ACTIONS, KnessetAction, KnessetPersona
from .base_platform import BasePlatform, PlatformAction

logger = logging.getLogger("mirofish.knesset.platforms.plenum")

# Maps LLM action names to ParliamentState handler keys
_ACTION_ALIAS: Dict[str, str] = {
    "SPEAK_IN_PLENUM": "SPEAK",
}


class PlenumPlatform(BasePlatform):
    """Full Knesset plenum simulation platform.

    Actions include legislation, voting, speeches, lobbying, alliances,
    amendments, defections, and inaction.  Prompts are generated in Hebrew
    and responses are expected as a single JSON object.
    """

    PLATFORM_ID: str = "plenum"
    ACTIONS: List[str] = list(KNESSET_ACTIONS)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def build_prompt(
        self,
        persona: KnessetPersona,
        round_num: int,
        max_rounds: int,
        parliament_summary: str,
        memory_context: str,
        injected_text: str,
        *,
        pending_bills: list | None = None,
    ) -> str:
        """Build the Hebrew plenum prompt for a single MK round."""
        coalition_status = "קואליציה" if persona.coalition_member else "אופוזיציה"

        committees = ""
        if persona.committee_roles:
            committees = "\nתפקידים בוועדות: " + ", ".join(persona.committee_roles)

        stances_formatted = "\n".join(
            f"- {topic}: {stance}" for topic, stance in persona.stances.items()
        )

        memory_block = ""
        if memory_context:
            memory_block = f"\n--- זיכרון ---\n{memory_context}\n"

        injected_block = ""
        if injected_text:
            injected_block = f"\n--- הזרקת אירוע ---\n{injected_text}\n"

        # Build voting directive if there are bills pending vote
        voting_directive = ""
        if pending_bills:
            bills_list = "\n".join(
                f'  • "{b["title"]}" [bill_id: {b["id"]}] — שלב: {b["status"]}'
                for b in pending_bills
            )
            voting_directive = (
                f"\n⚠️ הצעות חוק מחכות להצבעה שלך:\n{bills_list}\n"
                f"חובה להצביע! בחר VOTE עם bill_id מהרשימה למעלה.\n"
                f"אתה חייב להצביע בעד, נגד, או נמנע — בהתאם לעמדותיך ולאינטרסים של סיעתך.\n"
            )

        return (
            f"אתה {persona.name_he}, חבר כנסת מסיעת {persona.faction}.\n"
            f"מעמד: {coalition_status} | השפעה: {persona.influence_score}/100 "
            f"| נאמנות סיעתית: {persona.loyalty_score:.0%}\n"
            f"סגנון רטורי: {persona.rhetoric_style}{committees}\n"
            f"\nרקע אישי:\n{persona.personality}\n"
            f"\nעמדותיך העקריות:\n{stances_formatted}\n"
            f"{memory_block}"
            f"--- מצב הכנסת ---\n{parliament_summary}\n"
            f"{voting_directive}"
            f"{injected_block}"
            f"--- סבב {round_num} מתוך {max_rounds} ---\n\n"
            "פעולות אפשריות:\n"
            "- VOTE — הצבע בעד/נגד/נמנע על הצעת חוק (עדיפות עליונה כשיש הצעה פעילה!)\n"
            "- SPEAK_IN_PLENUM — נאם במליאה לפני ההצבעה\n"
            "- LOBBY — שכנע חבר כנסת אחר לשנות עמדה\n"
            "- PROPOSE_BILL — הצע הצעת חוק חדשה\n"
            "- AMEND_BILL — הצע תיקון להצעת חוק\n"
            "- FORM_ALLIANCE — הצע ברית בין-סיעתית\n"
            "- DEFECT — עזוב את הסיעה/הקואליציה\n"
            "- DO_NOTHING — שב בשקט\n\n"
            "השב בפורמט JSON בלבד:\n"
            '{"action": "VOTE", "bill_id": "<bill_id מהרשימה>", '
            '"vote": "בעד/נגד/נמנע", "reasoning": "<נימוק קצר בעברית>"}\n'
            "או פעולה אחרת בפורמט:\n"
            '{"action": "SPEAK_IN_PLENUM", "speech": "<תוכן הנאום>", '
            '"reasoning": "<נימוק>"}'
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def parse_action(
        self,
        raw_response: str,
        persona: KnessetPersona,
        round_num: int,
    ) -> PlatformAction:
        """Parse an LLM JSON response into a validated PlatformAction."""
        data = self._extract_json(raw_response)

        if not data:
            logger.warning(
                "Could not parse JSON from %s (round %d), falling back to DO_NOTHING",
                persona.name_he, round_num,
            )
            return PlatformAction(action_type="DO_NOTHING", raw_data={"reasoning": raw_response[:200]})

        raw_action = data.get("action", "DO_NOTHING")
        validated = self._validate_action_type(raw_action)

        return PlatformAction(action_type=validated, raw_data=data)

    # ------------------------------------------------------------------
    # State application
    # ------------------------------------------------------------------

    def apply_action(
        self,
        parliament_state: Any,
        mk_id: str,
        mk_name: str,
        action: PlatformAction,
        round_num: int,
    ) -> None:
        """Apply a plenum action to ParliamentState.

        Maps action aliases (e.g. SPEAK_IN_PLENUM -> SPEAK) before
        delegating to ``parliament_state.apply_action``.
        """
        dispatch_type = _ACTION_ALIAS.get(action.action_type, action.action_type)

        knesset_action = KnessetAction(
            round_num=round_num,
            timestamp="",  # filled by ParliamentState
            agent_id=mk_id,
            agent_name=mk_name,
            action_type=dispatch_type,
            bill_id=action.bill_id,
            vote_value=action.vote_value,
            speech_text=action.speech_text,
            reasoning=action.reasoning,
            target_mk_id=action.target_mk_id,
        )

        parliament_state.apply_action(mk_id, mk_name, knesset_action)

    # ------------------------------------------------------------------
    # State summary
    # ------------------------------------------------------------------

    def get_state_summary(self, persona_id: str) -> str:
        """Return platform-specific state summary.

        The plenum platform has no extra per-persona state beyond what
        ParliamentState already tracks, so this returns an empty string.
        """
        return ""
