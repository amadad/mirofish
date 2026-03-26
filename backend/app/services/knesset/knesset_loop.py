"""KnessetLoop — core simulation engine for KnessetSim.

Forked from FastAgentLoop, adapted for Israeli parliamentary simulation.
Processes Knesset MK personas in async batches, delegates prompt building
and action parsing to pluggable Platform instances, and applies actions
to ParliamentState.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .parliament_state import ParliamentState
from .platforms.base_platform import BasePlatform
from .types import KNESSET_ACTIONS, KnessetAction, KnessetPersona

logger = logging.getLogger("mirofish.knesset.knesset_loop")

# Maps LLM action names to ParliamentState handler keys (legacy compat)
_ACTION_ALIAS = {
    "SPEAK_IN_PLENUM": "SPEAK",
}


class KnessetLoop:
    """Async batch Knesset simulation engine.

    Orchestrates rounds of MK decision-making: delegates prompt building
    and action parsing to the configured Platform, calls the LLM router,
    applies actions to ParliamentState, and advances bills each round.

    Parameters
    ----------
    router : Any
        LLM router for API calls.
    personas : list[KnessetPersona]
        MK personas participating in the simulation.
    parliament_state : ParliamentState
        Shared parliament state tracking bills, votes, coalitions.
    platform : BasePlatform | None
        Pluggable interaction mode (plenum, roundtable, negotiation, etc.).
        If None, uses PlenumPlatform as default.
    max_rounds : int
        Number of simulation rounds.
    batch_size : int
        Max concurrent LLM calls per batch.
    injector : Any | None
        Optional data injector for real-world events.
    memory_store : Any | None
        Optional memory store for cross-round agent memory.
    """

    def __init__(
        self,
        router,
        personas: List[KnessetPersona],
        parliament_state: ParliamentState,
        platform: Optional[BasePlatform] = None,
        max_rounds: int = 5,
        batch_size: int = 50,
        injector: Optional[Any] = None,
        memory_store: Optional[Any] = None,
        social_layer: Optional[Any] = None,
    ) -> None:
        self.router = router
        self.personas = personas
        self.parliament_state = parliament_state
        self.max_rounds = max_rounds
        self.batch_size = batch_size
        self.injector = injector
        self.memory_store = memory_store
        self.social_layer = social_layer

        # Platform — default to PlenumPlatform for backward compatibility
        if platform is not None:
            self.platform = platform
        else:
            from .platforms.plenum import PlenumPlatform
            self.platform = PlenumPlatform()

        # Accumulated actions across all rounds
        self.all_actions: List[KnessetAction] = []
        # Per-round action lists for get_round_summary
        self._round_actions: Dict[int, List[KnessetAction]] = {}
        # Per-round bill advancement messages
        self._round_bill_changes: Dict[int, List[str]] = {}

    # ------------------------------------------------------------------
    # Prompt building (delegates to platform)
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        persona: KnessetPersona,
        round_num: int,
        injected_text: str = "",
    ) -> str:
        """Build a Hebrew prompt for a single MK persona via the platform."""

        # Memory context (optional)
        memory_context = ""
        if self.memory_store is not None:
            try:
                memories = self.memory_store.get(persona.agent_id)
                if memories:
                    memory_context = f"\nזיכרון מסבבים קודמים:\n{memories}\n"
            except Exception as e:
                logger.warning("Memory fetch failed for %s: %s", persona.agent_id, e)

        # Parliament summary (personalized)
        parliament_summary = self.parliament_state.get_parliament_summary(persona.agent_id)

        # Collect pending bills that need votes
        pending_bills = []
        for bid, bill in self.parliament_state.bills.items():
            if bill.status in ("first_reading", "second_reading", "third_reading"):
                pending_bills.append({
                    "id": bid,
                    "title": bill.title_he,
                    "status": bill.status,
                })

        return self.platform.build_prompt(
            persona=persona,
            round_num=round_num,
            max_rounds=self.max_rounds,
            parliament_summary=parliament_summary,
            memory_context=memory_context,
            injected_text=injected_text,
            pending_bills=pending_bills,
        )

    # ------------------------------------------------------------------
    # Response parsing (delegates to platform)
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        text: str,
        persona: KnessetPersona,
        round_num: int,
    ) -> KnessetAction:
        """Parse LLM response via platform, convert to KnessetAction."""
        platform_action = self.platform.parse_action(text, persona, round_num)
        return self.platform.to_knesset_action(platform_action, persona, round_num)

    # ------------------------------------------------------------------
    # Single round execution
    # ------------------------------------------------------------------

    async def run_round(self, round_num: int) -> List[dict]:
        """Run one simulation round — all MKs decide in parallel batches.

        Returns list of action dicts for this round.
        """
        self.parliament_state.current_round = round_num
        actions: List[KnessetAction] = []

        # Fetch injected real-world events for this round
        injected_text = ""
        if self.injector is not None:
            try:
                events = self.injector.get_events_for_round(round_num)
                injected_text = self.injector.format_for_feed(events)
            except Exception as e:
                logger.warning("Data injector error in round %d: %s", round_num, e)

        # Process personas in batches
        for batch_start in range(0, len(self.personas), self.batch_size):
            batch = self.personas[batch_start : batch_start + self.batch_size]
            prompts = [self._build_prompt(p, round_num, injected_text) for p in batch]

            # Fire LLM calls concurrently within this batch
            async def _call_llm(prompt: str) -> str:
                try:
                    resp = self.router.chat(
                        task_type="knesset_decision",
                        messages=[{"role": "user", "content": prompt}],
                    )
                    return resp
                except Exception as e:
                    logger.warning("LLM call failed: %s", e)
                    return '{"action": "DO_NOTHING"}'

            tasks = [_call_llm(p) for p in prompts]
            responses = await asyncio.gather(*tasks)

            for persona, resp in zip(batch, responses):
                action = self._parse_response(resp, persona, round_num)

                # Apply via platform (handles platform-specific state)
                platform_action = self.platform.parse_action(resp, persona, round_num)
                self.platform.apply_action(
                    self.parliament_state,
                    action.agent_id,
                    action.agent_name,
                    platform_action,
                    round_num,
                )
                actions.append(action)

        # Advance bills after all agents have acted
        bill_changes = self.parliament_state.advance_bills()
        if bill_changes:
            for msg in bill_changes:
                logger.info("Round %d bill change: %s", round_num, msg)

        # Save round state
        self._round_actions[round_num] = actions
        self._round_bill_changes[round_num] = bill_changes
        self.all_actions.extend(actions)

        # Persist to memory store if available
        if self.memory_store is not None:
            try:
                for action in actions:
                    if action.action_type != "DO_NOTHING":
                        self.memory_store.save(
                            action.agent_id,
                            round_num,
                            action.to_dict(),
                        )
            except Exception as e:
                logger.warning("Memory store save failed in round %d: %s", round_num, e)

        # Run social layer if enabled
        social_tweets = []
        if self.social_layer is not None:
            try:
                social_tweets = await self.social_layer.process_round(
                    round_num, [a.to_dict() for a in actions]
                )
                logger.info("Round %d: %d social tweets generated", round_num, len(social_tweets))
            except Exception as e:
                logger.warning("Social layer failed in round %d: %s", round_num, e)

        logger.info(
            "Round %d complete: %d actions, %d bill changes (platform=%s)",
            round_num, len(actions), len(bill_changes), self.platform.PLATFORM_ID,
        )

        return [a.to_dict() for a in actions]

    # ------------------------------------------------------------------
    # Full simulation run
    # ------------------------------------------------------------------

    async def run(
        self,
        on_round_complete: Optional[Callable[[int, List[dict]], None]] = None,
    ) -> List[dict]:
        """Run full simulation across all rounds.

        Args:
            on_round_complete: Optional callback(round_num, action_dicts) after each round.

        Returns:
            List of all action dicts across all rounds.
        """
        for round_num in range(1, self.max_rounds + 1):
            action_dicts = await self.run_round(round_num)
            if on_round_complete:
                on_round_complete(round_num, action_dicts)

        return [a.to_dict() for a in self.all_actions]

    # ------------------------------------------------------------------
    # Round summary
    # ------------------------------------------------------------------

    def get_round_summary(self, round_num: int) -> dict:
        """Summary of what happened in a specific round.

        Returns dict with action counts by type, bills advanced, votes recorded,
        and platform-specific state summary.
        """
        actions = self._round_actions.get(round_num, [])
        bill_changes = self._round_bill_changes.get(round_num, [])

        # Count actions by type
        action_counts: Dict[str, int] = Counter(a.action_type for a in actions)

        # Count votes by value
        vote_counts: Dict[str, int] = Counter(
            a.vote_value for a in actions
            if a.action_type == "VOTE" and a.vote_value
        )

        # Bills proposed this round
        bills_proposed = [
            a.bill_id or f"(unnamed by {a.agent_name})"
            for a in actions
            if a.action_type == "PROPOSE_BILL"
        ]

        return {
            "round_num": round_num,
            "platform": self.platform.PLATFORM_ID,
            "total_actions": len(actions),
            "action_counts": dict(action_counts),
            "vote_counts": dict(vote_counts),
            "bills_proposed": bills_proposed,
            "bills_advanced": bill_changes,
            "active_mks": len([a for a in actions if a.action_type != "DO_NOTHING"]),
            "idle_mks": len([a for a in actions if a.action_type == "DO_NOTHING"]),
            "social_tweet_count": len(self.social_layer.round_tweets.get(round_num, [])) if self.social_layer else 0,
        }
