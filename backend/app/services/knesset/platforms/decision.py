"""DecisionPlatform — structured decision-making interaction mode.

Simulates a committee decision flow in three phases:
1. ANALYZE (rounds 1-2) — agents examine options objectively
2. DEBATE  (rounds 3-4) — agents advocate for / against options
3. VOTE    (rounds 5+)  — agents vote, with supermajority (>2/3) required

If no supermajority is reached after a voting round, DEFER becomes available.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..types import KnessetAction, KnessetPersona
from .base_platform import BasePlatform, PlatformAction

logger = logging.getLogger("mirofish.knesset.platforms.decision")

# Phase boundaries
_ANALYZE_END = 2
_DEBATE_END = 4


def _phase_for_round(round_num: int) -> str:
    """Return the phase name for a given round number."""
    if round_num <= _ANALYZE_END:
        return "analyze"
    if round_num <= _DEBATE_END:
        return "debate"
    return "vote"


def _phase_name_he(phase: str) -> str:
    return {"analyze": "ניתוח", "debate": "דיון", "vote": "הצבעה"}.get(phase, phase)


class DecisionPlatform(BasePlatform):
    """Structured committee decision platform.

    Agents analyze options, debate them, then vote.  A supermajority
    (>2/3) is required for a decision; otherwise agents may defer.
    """

    PLATFORM_ID: str = "decision"
    ACTIONS: List[str] = [
        "ANALYZE",
        "ADVOCATE",
        "DEVIL_ADVOCATE",
        "VOTE",
        "ABSTAIN",
        "DEFER",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.platform_state: Dict[str, Any] = {
            "decision_topic": "",
            "options": [],           # [{option_id, text_he, proposer_id}]
            "analysis_log": [],      # [{agent_id, agent_name, option_id, analysis_he, stance}]
            "devil_advocates": {},   # agent_id -> option_id
            "votes": {},             # round_num -> {agent_id -> option_id}
            "deferred_to": None,
            "phase": "analyze",
            "decision": None,        # winning option_id after supermajority
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_topic(self, parliament_summary: str) -> None:
        """Set the decision topic from parliament summary on first call."""
        if not self.platform_state["decision_topic"]:
            self.platform_state["decision_topic"] = parliament_summary

    def _update_phase(self, round_num: int) -> None:
        self.platform_state["phase"] = _phase_for_round(round_num)

    def _format_options(self) -> str:
        options = self.platform_state["options"]
        if not options:
            return "  אין אפשרויות מוגדרות"
        return "\n".join(
            f"  [{o['option_id']}] {o['text_he']}" for o in options
        )

    def _format_analysis_log(self, limit: int = 5) -> str:
        log = self.platform_state["analysis_log"][-limit:]
        if not log:
            return "  אין ניתוחים עדיין"
        return "\n".join(
            f"  {e['agent_name']} [{e.get('stance', '?')}] "
            f"אפשרות {e.get('option_id', '?')}: {e.get('analysis_he', '')[:80]}"
            for e in log
        )

    def _format_vote_tally(self) -> str:
        votes = self.platform_state["votes"]
        if not votes:
            return ""
        # Aggregate across all vote rounds
        tally: Dict[str, int] = {}
        total = 0
        for round_votes in votes.values():
            for _agent_id, option_id in round_votes.items():
                if option_id == "__abstain__":
                    continue
                tally[option_id] = tally.get(option_id, 0) + 1
                total += 1

        if not tally:
            return ""
        lines = ["\nתוצאות הצבעה עד כה:"]
        for opt_id, count in sorted(tally.items(), key=lambda x: -x[1]):
            pct = f"{count / total:.0%}" if total else "0%"
            lines.append(f"  [{opt_id}] — {count} קולות ({pct})")
        return "\n".join(lines)

    def _check_supermajority(self) -> Optional[str]:
        """Return winning option_id if any option has >2/3 of votes, else None."""
        votes = self.platform_state["votes"]
        tally: Dict[str, int] = {}
        total = 0
        for round_votes in votes.values():
            for option_id in round_votes.values():
                if option_id == "__abstain__":
                    total += 1
                    continue
                tally[option_id] = tally.get(option_id, 0) + 1
                total += 1
        if total == 0:
            return None
        for opt_id, count in tally.items():
            if count / total > 2 / 3:
                return opt_id
        return None

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
    ) -> str:
        self._ensure_topic(parliament_summary)
        self._update_phase(round_num)

        phase = self.platform_state["phase"]
        coalition_status = "קואליציה" if persona.coalition_member else "אופוזיציה"

        stances_formatted = "\n".join(
            f"- {topic}: {stance}" for topic, stance in persona.stances.items()
        )

        memory_block = ""
        if memory_context:
            memory_block = f"\n--- זיכרון ---\n{memory_context}\n"

        injected_block = ""
        if injected_text:
            injected_block = f"\n--- הזרקת אירוע ---\n{injected_text}\n"

        vote_tally = self._format_vote_tally() if phase == "vote" else ""

        # Phase-specific instructions
        if phase == "analyze":
            phase_instruction = (
                "שלב ניתוח — נתח את האפשרויות באופן אובייקטיבי. "
                "מומלץ: ANALYZE."
            )
        elif phase == "debate":
            phase_instruction = (
                "שלב דיון — טען בעד או נגד אפשרויות. "
                "מומלץ: ADVOCATE או DEVIL_ADVOCATE."
            )
        else:
            has_supermajority = self._check_supermajority() is not None
            if has_supermajority:
                phase_instruction = "שלב הצבעה — יש רוב על. ניתן להצביע לאישור."
            else:
                phase_instruction = (
                    "שלב הצבעה — הצבע, הימנע, או דחה את ההחלטה. "
                    "אין רוב על (>2/3) עדיין — DEFER זמין."
                )

        return (
            f"אתה {persona.name_he}, חבר ועדה מקבלת החלטות.\n"
            f"סיעת {persona.faction} | {coalition_status}\n"
            f"\nעמדותיך:\n{stances_formatted}\n"
            f"{memory_block}"
            f"\n--- נושא ההחלטה ---\n"
            f"{self.platform_state['decision_topic']}\n"
            f"\nאפשרויות:\n{self._format_options()}\n"
            f"\n--- שלב: {_phase_name_he(phase)} (סבב {round_num}/{max_rounds}) ---\n"
            f"\nניתוחים עד כה:\n{self._format_analysis_log()}\n"
            f"{vote_tally}\n"
            f"{injected_block}"
            f"\n{phase_instruction}\n\n"
            "בחר פעולה:\n"
            "- ANALYZE — נתח אפשרות (בעד/נגד/ניטרלי)\n"
            "- ADVOCATE — תמוך באפשרות\n"
            "- DEVIL_ADVOCATE — שחק פרקליט שטן נגד אפשרות\n"
            "- VOTE — הצבע לאפשרות\n"
            "- ABSTAIN — הימנע מהצבעה\n"
            "- DEFER — דחה את ההחלטה\n\n"
            "השב בפורמט JSON בלבד:\n"
            '{"action": "...", "option_id": "...", "analysis": "...", '
            '"stance": "pro/con/neutral", "defer_to": "...", "reasoning": "..."}'
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
        data = self._extract_json(raw_response)

        if not data:
            logger.warning(
                "Could not parse JSON from %s (round %d), falling back to ANALYZE",
                persona.name_he, round_num,
            )
            return PlatformAction(
                action_type="ANALYZE",
                raw_data={"reasoning": raw_response[:200]},
            )

        raw_action = data.get("action", "ANALYZE")
        validated = self._validate_action_type(raw_action)

        phase = _phase_for_round(round_num)

        # Downgrade VOTE/ABSTAIN/DEFER in non-vote phases
        if phase in ("analyze", "debate") and validated in ("VOTE", "ABSTAIN", "DEFER"):
            logger.info(
                "Downgrading %s to ANALYZE for %s — not in vote phase yet",
                validated, persona.name_he,
            )
            validated = "ANALYZE"

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
        act = action.action_type
        data = action.raw_data
        option_id = data.get("option_id", "")
        analysis = data.get("analysis", "")
        stance = data.get("stance", "neutral")
        reasoning = data.get("reasoning", "")
        content = analysis or reasoning

        if act == "ANALYZE":
            self.platform_state["analysis_log"].append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "option_id": option_id,
                "analysis_he": analysis,
                "stance": stance,
            })

        elif act == "ADVOCATE":
            self.platform_state["analysis_log"].append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "option_id": option_id,
                "analysis_he": analysis,
                "stance": "pro",
            })

        elif act == "DEVIL_ADVOCATE":
            self.platform_state["devil_advocates"][mk_id] = option_id
            self.platform_state["analysis_log"].append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "option_id": option_id,
                "analysis_he": f"[פרקליט שטן] {analysis}",
                "stance": "con",
            })

        elif act == "VOTE":
            round_votes = self.platform_state["votes"].setdefault(round_num, {})
            round_votes[mk_id] = option_id
            # Check supermajority after each vote
            winner = self._check_supermajority()
            if winner:
                self.platform_state["decision"] = winner
                logger.info("Supermajority reached for option %s", winner)

        elif act == "ABSTAIN":
            round_votes = self.platform_state["votes"].setdefault(round_num, {})
            round_votes[mk_id] = "__abstain__"

        elif act == "DEFER":
            defer_to = data.get("defer_to", "")
            self.platform_state["deferred_to"] = defer_to
            self.platform_state["analysis_log"].append({
                "agent_id": mk_id,
                "agent_name": mk_name,
                "option_id": "",
                "analysis_he": f"דחיית החלטה — {defer_to}" if defer_to else "דחיית החלטה",
                "stance": "neutral",
            })

        # Record to parliament state
        if content:
            knesset_action = KnessetAction(
                round_num=round_num,
                timestamp="",
                agent_id=mk_id,
                agent_name=mk_name,
                action_type=act,
                speech_text=content,
                reasoning=reasoning,
            )
            parliament_state.apply_action(mk_id, mk_name, knesset_action)

    # ------------------------------------------------------------------
    # State summary
    # ------------------------------------------------------------------

    def get_state_summary(self, persona_id: str) -> str:
        phase = self.platform_state["phase"]
        analysis_count = len(self.platform_state["analysis_log"])
        total_votes = sum(
            len(rv) for rv in self.platform_state["votes"].values()
        )
        return f"החלטה: שלב {_phase_name_he(phase)}, {analysis_count} ניתוחים, {total_votes} הצבעות"
