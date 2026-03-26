"""KnessetChat — interactive conversation with MK personas.

Enables 1-on-1 chat with individual MK personas and multi-MK group
discussions on a given topic. Each interaction uses the MK's full
persona context, memory, and current parliament state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .parliament_state import ParliamentState
from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.chat_interface")


class KnessetChat:
    """Interactive conversation interface with Knesset MK personas.

    Supports 1-on-1 MK chat and multi-MK group discussions. Each
    interaction builds a contextual Hebrew prompt with the MK's
    persona, memory, and parliament state.

    Parameters
    ----------
    router : LLMRouter
        The LLM router instance for chat calls.
    personas : list[KnessetPersona]
        List of available MK personas.
    memory_store : Any | None
        Optional memory store for conversation history.
    parliament_state : ParliamentState | None
        Optional current parliament state for context.
    """

    def __init__(
        self,
        router,
        personas: List[KnessetPersona],
        memory_store=None,
        parliament_state: Optional[ParliamentState] = None,
    ) -> None:
        self.router = router
        self.personas = personas
        self.memory_store = memory_store
        self.parliament_state = parliament_state or ParliamentState()

        # Index personas by ID and faction for quick lookup
        self._by_id: Dict[str, KnessetPersona] = {
            p.agent_id: p for p in personas
        }
        self._by_faction: Dict[str, List[KnessetPersona]] = {}
        for p in personas:
            self._by_faction.setdefault(p.faction, []).append(p)

        # Per-MK chat history: mk_id -> [{role, content}]
        self._chat_history: Dict[str, List[dict]] = {}

    # ------------------------------------------------------------------
    # Public API — 1-on-1 chat
    # ------------------------------------------------------------------

    async def chat_with_mk(
        self,
        mk_id: str,
        message_he: str,
        context: Optional[dict] = None,
    ) -> str:
        """Chat with a single MK persona.

        Parameters
        ----------
        mk_id : str
            The MK's agent_id.
        message_he : str
            User's message in Hebrew.
        context : dict | None
            Optional additional context (e.g., bill_id being discussed).

        Returns
        -------
        str
            The MK's response in Hebrew.
        """
        persona = self.get_mk_by_id(mk_id)
        if persona is None:
            return f"שגיאה: לא נמצא ח\"כ עם מזהה {mk_id}"

        # Get chat history for this MK
        history = self._chat_history.get(mk_id, [])

        # Build prompt
        prompt = self._build_chat_prompt(persona, message_he, history)

        # Call LLM
        try:
            response = self.router.chat(
                task_type="knesset_chat",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.error("Chat with %s failed: %s", persona.name_he, e)
            return f"שגיאה בתקשורת עם ח\"כ {persona.name_he}: {e}"

        # Save to history
        if mk_id not in self._chat_history:
            self._chat_history[mk_id] = []
        self._chat_history[mk_id].append({"role": "user", "content": message_he})
        self._chat_history[mk_id].append({"role": "mk", "content": response})

        # Trim history to last 20 exchanges to avoid prompt bloat
        if len(self._chat_history[mk_id]) > 40:
            self._chat_history[mk_id] = self._chat_history[mk_id][-40:]

        # Save to memory store if available
        if self.memory_store is not None:
            try:
                self.memory_store.save(
                    mk_id, 0,
                    {"type": "chat", "user": message_he, "response": response[:500]},
                )
            except Exception as e:
                logger.warning("Memory save failed for %s: %s", mk_id, e)

        return response

    # ------------------------------------------------------------------
    # Public API — group discussion
    # ------------------------------------------------------------------

    async def group_discussion(
        self,
        mk_ids: List[str],
        topic_he: str,
        turns: int = 5,
    ) -> List[dict]:
        """Run a multi-MK group discussion on a topic.

        Each MK speaks in turn, seeing all previous speakers' statements.

        Parameters
        ----------
        mk_ids : list[str]
            List of MK agent_ids to participate.
        topic_he : str
            Discussion topic in Hebrew.
        turns : int
            Number of discussion turns (default 5). Each turn cycles
            through all participating MKs.

        Returns
        -------
        list[dict]
            [{mk_id, mk_name, response_he, turn}]
        """
        participants = []
        for mk_id in mk_ids:
            persona = self.get_mk_by_id(mk_id)
            if persona:
                participants.append(persona)
            else:
                logger.warning("Group discussion: MK %s not found, skipping", mk_id)

        if not participants:
            return [{"error": "לא נמצאו חברי כנסת תקינים לדיון"}]

        discussion_log: List[dict] = []
        # Accumulated statements for context
        previous_statements: List[str] = []

        for turn in range(1, turns + 1):
            for persona in participants:
                # Build context from previous statements
                context_block = ""
                if previous_statements:
                    context_block = "\n".join(previous_statements[-10:])

                prompt = self._build_discussion_prompt(
                    persona, topic_he, turn, turns, context_block,
                )

                try:
                    response = self.router.chat(
                        task_type="knesset_chat",
                        messages=[{"role": "user", "content": prompt}],
                    )
                except Exception as e:
                    logger.error(
                        "Group discussion: %s failed in turn %d: %s",
                        persona.name_he, turn, e,
                    )
                    response = f"(ח\"כ {persona.name_he} לא הצליח/ה להגיב)"

                entry = {
                    "mk_id": persona.agent_id,
                    "mk_name": persona.name_he,
                    "faction": persona.faction,
                    "response_he": response,
                    "turn": turn,
                }
                discussion_log.append(entry)

                # Add to previous statements for next speaker
                preview = response[:150] + "..." if len(response) > 150 else response
                previous_statements.append(
                    f"ח\"כ {persona.name_he} ({persona.faction}): {preview}"
                )

        logger.info(
            "Group discussion complete: %d MKs, %d turns, %d statements",
            len(participants), turns, len(discussion_log),
        )

        return discussion_log

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_mk_by_id(self, mk_id: str) -> Optional[KnessetPersona]:
        """Find a persona by agent_id.

        Parameters
        ----------
        mk_id : str
            The MK's agent_id.

        Returns
        -------
        KnessetPersona | None
        """
        return self._by_id.get(mk_id)

    def get_mks_by_faction(self, faction: str) -> List[KnessetPersona]:
        """Filter personas by faction name.

        Parameters
        ----------
        faction : str
            Faction name in Hebrew (e.g., "ליכוד").

        Returns
        -------
        list[KnessetPersona]
        """
        # Exact match first
        if faction in self._by_faction:
            return list(self._by_faction[faction])

        # Substring match fallback
        results = []
        for f_name, members in self._by_faction.items():
            if faction in f_name or f_name in faction:
                results.extend(members)
        return results

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_chat_prompt(
        self,
        persona: KnessetPersona,
        message_he: str,
        history: Optional[List[dict]] = None,
    ) -> str:
        """Build a Hebrew chat prompt for a single MK persona.

        Parameters
        ----------
        persona : KnessetPersona
            The MK persona.
        message_he : str
            The user's message.
        history : list[dict] | None
            Previous chat exchanges [{role, content}].

        Returns
        -------
        str
            Complete Hebrew prompt.
        """
        # Format stances
        stances_lines = []
        for topic, position in persona.stances.items():
            stances_lines.append(f"- {topic}: {position}")
        stances_formatted = "\n".join(stances_lines) if stances_lines else "- (לא הוגדרו)"

        # Memory context
        memory_context = ""
        if self.memory_store is not None:
            try:
                memories = self.memory_store.get(persona.agent_id)
                if memories:
                    memory_context = f"\nזיכרון מאינטראקציות קודמות:\n{memories}\n"
            except Exception as e:
                logger.warning("Memory fetch failed for %s: %s", persona.agent_id, e)

        # Parliament context
        parliament_context = ""
        if self.parliament_state:
            parliament_context = self.parliament_state.get_parliament_summary(
                persona.agent_id,
            )

        # Chat history
        chat_history = ""
        if history:
            history_lines = []
            for entry in history[-10:]:
                role_label = "המשתמש" if entry["role"] == "user" else persona.name_he
                history_lines.append(f"{role_label}: {entry['content'][:200]}")
            chat_history = "\n".join(history_lines)

        # Coalition status
        coalition_status = "חבר קואליציה" if persona.coalition_member else "חבר אופוזיציה"

        prompt = f"""אתה {persona.name_he}, חבר כנסת מסיעת {persona.faction}.
מעמד: {coalition_status} | השפעה: {persona.influence_score}/100 | נאמנות סיעתית: {persona.loyalty_score:.0%}
סגנון רטורי: {persona.rhetoric_style}

{persona.personality}

עמדותיך:
{stances_formatted}
{memory_context}
--- מצב הכנסת ---
{parliament_context}

היסטוריית שיחה:
{chat_history}

המשתמש שואל: {message_he}

ענה בתור {persona.name_he}, בעברית, בהתאם לאישיותך ועמדותיך.
היה אותנטי לדמות — שמור על הסגנון הרטורי, ההשקפה הפוליטית והאישיות שלך."""

        return prompt

    def _build_discussion_prompt(
        self,
        persona: KnessetPersona,
        topic_he: str,
        turn: int,
        total_turns: int,
        previous_statements: str,
    ) -> str:
        """Build a Hebrew prompt for a group discussion turn.

        Parameters
        ----------
        persona : KnessetPersona
            The MK speaking this turn.
        topic_he : str
            Discussion topic.
        turn : int
            Current turn number.
        total_turns : int
            Total number of turns.
        previous_statements : str
            Formatted previous speakers' statements.

        Returns
        -------
        str
            Complete Hebrew prompt for this discussion turn.
        """
        stances_lines = []
        for topic, position in persona.stances.items():
            stances_lines.append(f"- {topic}: {position}")
        stances_formatted = "\n".join(stances_lines) if stances_lines else "- (לא הוגדרו)"

        coalition_status = "חבר קואליציה" if persona.coalition_member else "חבר אופוזיציה"

        previous_block = ""
        if previous_statements:
            previous_block = f"\n--- דברי חברי כנסת שדיברו לפניך ---\n{previous_statements}\n"

        prompt = f"""אתה {persona.name_he}, חבר כנסת מסיעת {persona.faction}.
מעמד: {coalition_status} | סגנון רטורי: {persona.rhetoric_style}

{persona.personality}

עמדותיך:
{stances_formatted}
{previous_block}
--- דיון בנושא: {topic_he} ---
סבב {turn} מתוך {total_turns}

דבר/י בנושא הדיון בתור {persona.name_he}.
התייחס/י לדברי חברי הכנסת שדיברו לפניך (אם יש).
היה/י אותנטי/ת לאישיותך, עמדותיך הפוליטיות וסגנונך הרטורי.
ענה/י בעברית, 2-4 משפטים."""

        return prompt
