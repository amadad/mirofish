"""NegotiationPlatform — coalition negotiation interaction mode.

Simulates multi-party negotiation dynamics: offers, counter-offers,
concessions, bluffs, walkouts, and deal acceptance.  Includes a bluff
detection mechanic weighted by agent loyalty scores.
"""

from __future__ import annotations

import logging
import random
import uuid
from typing import Any, Dict, List

from ..types import KnessetAction, KnessetPersona
from .base_platform import BasePlatform, PlatformAction

logger = logging.getLogger("mirofish.knesset.platforms.negotiation")


class NegotiationPlatform(BasePlatform):
    """Coalition negotiation platform.

    Agents exchange offers, counter-offers, concessions, and bluffs.
    Bluff detection accumulates suspicion per agent, weighted by loyalty.
    """

    PLATFORM_ID: str = "negotiation"
    ACTIONS: List[str] = [
        "OFFER",
        "COUNTER",
        "CONCEDE",
        "BLUFF",
        "WALK_AWAY",
        "ACCEPT",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.platform_state: Dict[str, Any] = {
            "offers_on_table": [],
            "negotiation_history": [],
            "deal_points": {},
            "bluff_tracker": {},
            "personas": {},
            "withdrawn": set(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _register_persona(self, persona: KnessetPersona) -> None:
        """Cache persona for bluff-detection lookups in apply_action."""
        if persona.agent_id not in self.platform_state["personas"]:
            self.platform_state["personas"][persona.agent_id] = persona

    def _open_offers(self) -> List[Dict[str, Any]]:
        return [
            o for o in self.platform_state["offers_on_table"]
            if o["status"] == "open"
        ]

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
        """Build the Hebrew negotiation prompt for a single MK round."""
        self._register_persona(persona)

        coalition_status = "קואליציה" if persona.coalition_member else "אופוזיציה"

        stances_formatted = "\n".join(
            f"- {topic}: {stance}" for topic, stance in persona.stances.items()
        )

        memory_block = ""
        if memory_context:
            memory_block = f"\n--- זיכרון ---\n{memory_context}\n"

        # Open offers
        open_offers = self._open_offers()
        if open_offers:
            offers_text = "\n".join(
                f"  [{o['offer_id'][:8]}] {o['agent_name']}: {o['terms_he']} (סבב {o['round_num']})"
                for o in open_offers
            )
        else:
            offers_text = "  אין הצעות פתוחות"

        # Deal points
        deal_points = self.platform_state["deal_points"]
        if deal_points:
            deals_text = "\n".join(
                f"  - {topic}: {agreement}" for topic, agreement in deal_points.items()
            )
        else:
            deals_text = "  אין עדיין"

        # Recent history (last 5)
        history = self.platform_state["negotiation_history"][-5:]
        if history:
            history_text = "\n".join(
                f"  [{h['round_num']}] {h['agent_name']} — {h['action_type']}: {h['content']}"
                for h in history
            )
        else:
            history_text = "  אין היסטוריה"

        injected_block = ""
        if injected_text:
            injected_block = f"\n--- הזרקת אירוע ---\n{injected_text}\n"

        return (
            f"אתה {persona.name_he}, מנהל משא ומתן בשם סיעת {persona.faction}.\n"
            f"{coalition_status} | השפעה: {persona.influence_score}/100\n"
            f"\nעמדותיך:\n{stances_formatted}\n"
            f"{memory_block}"
            f"\n--- מצב המשא ומתן ---\n{parliament_summary}\n"
            f"\nהצעות על השולחן:\n{offers_text}\n"
            f"\nנקודות שהוסכמו:\n{deals_text}\n"
            f"\nהיסטוריית מהלכים אחרונים:\n{history_text}\n"
            f"{injected_block}"
            f"\n--- סבב {round_num} מתוך {max_rounds} ---\n\n"
            "בחר מהלך:\n"
            "- OFFER — הצע הצעה חדשה\n"
            "- COUNTER — הצע הצעה נגדית\n"
            "- CONCEDE — ויתור על נקודה\n"
            "- BLUFF — בלוף (סיכון: עלול להיחשף!)\n"
            "- WALK_AWAY — צא מהמשא ומתן\n"
            "- ACCEPT — קבל הצעה\n\n"
            "השב בפורמט JSON בלבד:\n"
            '{"action": "...", "terms": "...", "target_offer_id": "...", "reasoning": "..."}'
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
                "Could not parse JSON from %s (round %d), falling back to ACCEPT",
                persona.name_he, round_num,
            )
            return PlatformAction(action_type="ACCEPT", raw_data={"reasoning": raw_response[:200]})

        raw_action = data.get("action", "ACCEPT")
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
        """Apply a negotiation action to platform state and parliament state."""
        act = action.action_type
        data = action.raw_data
        terms = data.get("terms", "")
        reasoning = data.get("reasoning", "")
        target_offer_id = data.get("target_offer_id", "")
        content = terms or reasoning

        if act == "OFFER":
            offer = {
                "offer_id": uuid.uuid4().hex[:12],
                "agent_id": mk_id,
                "agent_name": mk_name,
                "terms_he": terms,
                "round_num": round_num,
                "status": "open",
            }
            self.platform_state["offers_on_table"].append(offer)

        elif act == "COUNTER":
            # Mark the target offer as rejected, create a counter
            for o in self.platform_state["offers_on_table"]:
                if o["offer_id"].startswith(target_offer_id[:8]) and o["status"] == "open":
                    o["status"] = "rejected"
                    break
            counter = {
                "offer_id": uuid.uuid4().hex[:12],
                "agent_id": mk_id,
                "agent_name": mk_name,
                "terms_he": terms,
                "round_num": round_num,
                "status": "open",
            }
            self.platform_state["offers_on_table"].append(counter)

        elif act == "CONCEDE":
            # Move a point to deal_points
            if terms:
                topic = terms.split(":")[0].strip() if ":" in terms else f"ויתור_{round_num}"
                self.platform_state["deal_points"][topic] = terms

        elif act == "BLUFF":
            tracker = self.platform_state["bluff_tracker"]
            suspicion_increase = random.uniform(0.1, 0.3)
            tracker[mk_id] = tracker.get(mk_id, 0.0) + suspicion_increase

            # Check for detection
            persona = self.platform_state["personas"].get(mk_id)
            loyalty = persona.loyalty_score if persona else 0.5
            detected = random.random() < (tracker[mk_id] * (1 - loyalty))

            if tracker[mk_id] > 0.7:
                logger.warning(
                    "High bluff suspicion for %s: %.2f", mk_name, tracker[mk_id],
                )

            if detected:
                content = f"{content} [חשד לבלוף!]"
                self.platform_state["negotiation_history"].append({
                    "agent_id": mk_id,
                    "agent_name": mk_name,
                    "action_type": "BLUFF_DETECTED",
                    "content": f"חשד לבלוף! (רמת חשד: {tracker[mk_id]:.0%})",
                    "round_num": round_num,
                })

        elif act == "WALK_AWAY":
            self.platform_state["withdrawn"].add(mk_id)

        elif act == "ACCEPT":
            # Accept a target offer, move its terms to deal_points
            for o in self.platform_state["offers_on_table"]:
                if o["offer_id"].startswith(target_offer_id[:8]) and o["status"] == "open":
                    o["status"] = "accepted"
                    topic = o["terms_he"][:30] if o["terms_he"] else f"הסכמה_{round_num}"
                    self.platform_state["deal_points"][topic] = o["terms_he"]
                    break

        # Record to negotiation history
        self.platform_state["negotiation_history"].append({
            "agent_id": mk_id,
            "agent_name": mk_name,
            "action_type": act,
            "content": content,
            "round_num": round_num,
        })

        # Record speech in parliament state if there's content
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
        """Return a Hebrew summary of negotiation state for this persona."""
        open_count = len(self._open_offers())
        deal_count = len(self.platform_state["deal_points"])
        return f'מו"מ: {open_count} הצעות פתוחות, {deal_count} נקודות הסכמה'
