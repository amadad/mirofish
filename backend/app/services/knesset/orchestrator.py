"""KnessetOrchestrator — main entry point for all Knesset simulations.

Coordinates persona loading, parliament state setup, scenario application,
simulation execution via KnessetLoop, and report generation.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .knesset_loop import KnessetLoop
from .memory_store import KnessetMemoryStore
from .parliament_state import ParliamentState
from .persona_generator import KnessetPersonaGenerator
from .rzmapper_bridge import RZMapperBridge
from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.orchestrator")

# ---------------------------------------------------------------------------
# 25th Knesset coalition configuration (default)
# ---------------------------------------------------------------------------

_DEFAULT_COALITION = {
    "coalition_factions": ["ליכוד", "ש\"ס", "יהדות התורה", "הציונות הדתית", "עוצמה יהודית", "נועם"],
    "opposition_factions": [
        "יש עתיד", "מחנה ממלכתי", "ישראל ביתנו", "העבודה",
        "הרשימה המשותפת", "רע\"ם", "בל\"ד",
    ],
    "coalition_seats": 64,
    "opposition_seats": 56,
    "seats_by_faction": {
        "ליכוד": 32,
        "יש עתיד": 24,
        "הציונות הדתית": 7,
        "מחנה ממלכתי": 12,
        "ש\"ס": 11,
        "יהדות התורה": 7,
        "ישראל ביתנו": 6,
        "רע\"ם": 5,
        "העבודה": 4,
        "עוצמה יהודית": 6,
        "הרשימה המשותפת": 5,
        "נועם": 1,
    },
}


class KnessetOrchestrator:
    """Main entry point for all Knesset simulations.

    Coordinates the full simulation lifecycle: question parsing, persona
    loading, parliament state setup, scenario application, loop execution,
    and report generation.

    Parameters
    ----------
    router : LLMRouter
        The LLM router instance for all API calls.
    graph_storage : Any
        Graph storage for entity enrichment.
    memory_store : Any | None
        Optional memory store for cross-round agent memory.
    hybrid_search : Any | None
        Optional hybrid search for historical precedent lookup.
    injector : Any | None
        Optional data injector for real-world event injection.
    """

    def __init__(
        self,
        router,
        graph_storage,
        memory_store=None,
        hybrid_search=None,
        injector=None,
        rzmapper_bridge: Optional[RZMapperBridge] = None,
    ) -> None:
        self.router = router
        self.graph_storage = graph_storage
        self.hybrid_search = hybrid_search
        self.injector = injector

        # Memory store — use provided or create default SQLite-backed store
        if memory_store is not None:
            self.memory_store = memory_store
        else:
            self.memory_store = KnessetMemoryStore()

        # RZMAPPER bridge — use provided or create default
        if rzmapper_bridge is not None:
            self.rzmapper_bridge = rzmapper_bridge
        else:
            try:
                self.rzmapper_bridge = RZMapperBridge()
                logger.info("RZMAPPER bridge initialized (dir: %s)", self.rzmapper_bridge._rzmapper_dir)
            except Exception as e:
                logger.warning("RZMAPPER bridge unavailable: %s", e)
                self.rzmapper_bridge = None

        self._persona_generator = KnessetPersonaGenerator(
            router=router, graph_storage=graph_storage,
        )

        # In-memory simulation store: simulation_id -> result dict
        self._simulations: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_simulation(
        self,
        question_he: str,
        rounds: int = 5,
        scenario: Optional[dict] = None,
        platform: str = "plenum",
        social_layer: bool = True,
    ) -> dict:
        """Run a full Knesset simulation for a proposed bill.

        Parameters
        ----------
        question_he : str
            Hebrew question describing the proposed bill / legislation.
        rounds : int
            Number of simulation rounds (default 5).
        scenario : dict | None
            Optional scenario override (election change, crisis, etc.).
        platform : str
            Simulation platform: "plenum" (default), "roundtable",
            "negotiation", "brainstorm", or "decision".

        Returns
        -------
        dict
            Full simulation result with simulation_id, question, rounds_data,
            final_state, bill_outcomes, and summary.
        """
        simulation_id = str(uuid.uuid4())[:12]
        logger.info("Starting simulation %s: %.80s", simulation_id, question_he)

        # Store initial status
        self._simulations[simulation_id] = {
            "simulation_id": simulation_id,
            "status": "running",
            "question": question_he,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # 1. Parse the question to extract bill details
            bill_info = self._parse_question(question_he)
            logger.info("Parsed bill: %s", bill_info.get("bill_title", "?"))

            # 2. Load MK personas (prefer RZMAPPER bridge, fallback to generator)
            personas = self._load_personas(scenario)
            logger.info("Loaded %d personas", len(personas))

            # Enrich personas with RZMAPPER relationship context
            if self.rzmapper_bridge is not None:
                for persona in personas:
                    try:
                        rel_context = self.rzmapper_bridge.build_relationship_context(persona.agent_id)
                        if rel_context:
                            persona.personality = f"{persona.personality}\nקשרים: {rel_context}"
                    except Exception as e:
                        logger.debug("Relationship enrichment failed for %s: %s", persona.name_he, e)

            # Start a memory episode for this simulation
            episode_id = None
            if self.memory_store is not None and hasattr(self.memory_store, "start_episode"):
                try:
                    episode_id = self.memory_store.start_episode(
                        simulation_id=simulation_id,
                        topic_he=question_he[:200],
                        platform=platform,
                    )
                    logger.info("Memory episode started: %s", episode_id)
                except Exception as e:
                    logger.warning("Failed to start memory episode: %s", e)

            # 3. Setup parliament state with coalition map
            parliament_state = ParliamentState()
            coalition_config = self._setup_coalition()

            parliament_state.coalition_factions = coalition_config["coalition_factions"]
            parliament_state.opposition_factions = coalition_config["opposition_factions"]
            parliament_state.coalition_seats = coalition_config["coalition_seats"]
            parliament_state.opposition_seats = coalition_config["opposition_seats"]
            for faction in coalition_config["coalition_factions"]:
                parliament_state.coalition_map[faction] = "coalition"
            for faction in coalition_config["opposition_factions"]:
                parliament_state.coalition_map[faction] = "opposition"

            # 4. Apply scenario modifications if provided
            if scenario:
                from .scenarios import KnessetScenarioEngine
                engine = KnessetScenarioEngine()
                scenario_type = scenario.get("type", "")
                scenario_params = scenario.get("params", {})
                if scenario_type:
                    personas, modified_coalition = engine.apply_scenario(
                        scenario_type, scenario_params, personas,
                        parliament_state.coalition_map,
                    )
                    # Update parliament state with scenario modifications
                    parliament_state.coalition_map = modified_coalition
                    parliament_state.coalition_factions = [
                        f for f, role in modified_coalition.items()
                        if role == "coalition"
                    ]
                    parliament_state.opposition_factions = [
                        f for f, role in modified_coalition.items()
                        if role == "opposition"
                    ]

            # 5. Inject user's proposed bill at round 1
            from .types import BillState
            user_bill_id = f"user_bill_{simulation_id}"
            parliament_state.bills[user_bill_id] = BillState(
                bill_id=user_bill_id,
                title_he=bill_info.get("bill_title", question_he[:60]),
                summary_he=bill_info.get("bill_summary", question_he),
                category=bill_info.get("category", "כללי"),
                sponsor_id="user",
                sponsor_name="המשתמש",
                status="first_reading",  # Skip proposed/committee — go straight to voting
                votes={"בעד": 0, "נגד": 0, "נמנע": 0},
            )

            # 6. Create and run KnessetLoop with selected platform
            platform_impl = self._get_platform(platform)

            # Create social layer if enabled
            social_layer_impl = None
            if social_layer:
                try:
                    from .social_layer import SocialLayer
                    # Gather auxiliary agents
                    auxiliary = []
                    try:
                        auxiliary.extend(self._persona_generator.generate_tycoon_personas())
                        auxiliary.extend(self._persona_generator.generate_activist_personas())
                        auxiliary.extend(self._persona_generator.generate_auxiliary_personas())
                    except Exception as e:
                        logger.warning("Auxiliary agent generation failed: %s", e)
                    social_layer_impl = SocialLayer(
                        router=self.router,
                        personas=personas,
                        auxiliary_agents=auxiliary,
                    )
                    logger.info("Social layer enabled with %d auxiliary agents", len(auxiliary))
                except Exception as e:
                    logger.warning("Social layer creation failed: %s", e)

            loop = KnessetLoop(
                router=self.router,
                personas=personas,
                parliament_state=parliament_state,
                platform=platform_impl,
                max_rounds=rounds,
                batch_size=50,
                injector=self.injector,
                memory_store=self.memory_store,
                social_layer=social_layer_impl,
            )

            rounds_data: List[dict] = []

            def _on_round(round_num: int, action_dicts: List[dict]) -> None:
                summary = loop.get_round_summary(round_num)
                rounds_data.append({
                    "round_num": round_num,
                    "actions": action_dicts,
                    "summary": summary,
                })

            all_actions = await loop.run(on_round_complete=_on_round)

            # 7. Generate report
            final_state = parliament_state.to_dict()
            bill_outcomes = {}
            for bid, bill in parliament_state.bills.items():
                bill_outcomes[bid] = {
                    "title_he": bill.title_he,
                    "status": bill.status,
                    "votes": bill.votes,
                }

            report = self._generate_report({
                "personas": personas,
                "parliament_state": parliament_state,
                "all_actions": all_actions,
                "bill_outcomes": bill_outcomes,
                "user_bill_id": user_bill_id,
            })

            # End memory episode with outcome summary
            if episode_id is not None and self.memory_store is not None:
                try:
                    ub = bill_outcomes.get(user_bill_id, {})
                    outcome = f"חוק {bill_info.get('bill_title', '?')}: {ub.get('status', '?')}"
                    self.memory_store.end_episode(episode_id, outcome)
                    logger.info("Memory episode ended: %s", episode_id)
                except Exception as e:
                    logger.warning("Failed to end memory episode: %s", e)

            result = {
                "simulation_id": simulation_id,
                "status": "completed",
                "question": question_he,
                "bill_info": bill_info,
                "platform": platform,
                "rounds": rounds,
                "rounds_data": rounds_data,
                "final_state": final_state,
                "bill_outcomes": bill_outcomes,
                "social_layer": {
                    "tweets": [t.to_dict() for t in social_layer_impl.all_tweets] if social_layer_impl else [],
                    "trending": social_layer_impl.get_trending() if social_layer_impl else [],
                    "engagement": social_layer_impl.get_engagement_stats() if social_layer_impl else {},
                } if social_layer else None,
                "summary": report,
                "started_at": self._simulations[simulation_id]["started_at"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }

            self._simulations[simulation_id] = result
            logger.info("Simulation %s completed", simulation_id)
            return result

        except Exception as e:
            logger.error("Simulation %s failed: %s", simulation_id, e, exc_info=True)
            self._simulations[simulation_id]["status"] = "failed"
            self._simulations[simulation_id]["error"] = str(e)
            raise

    def get_simulation_status(self, simulation_id: str) -> dict:
        """Return current state of a running/completed simulation.

        Parameters
        ----------
        simulation_id : str
            The simulation UUID.

        Returns
        -------
        dict
            Simulation state dict, or error if not found.
        """
        if simulation_id not in self._simulations:
            return {"error": f"Simulation {simulation_id} not found"}
        return self._simulations[simulation_id]

    # ------------------------------------------------------------------
    # Platform selection
    # ------------------------------------------------------------------

    def _get_platform(self, platform_name: str):
        """Instantiate a platform by name.

        Parameters
        ----------
        platform_name : str
            One of: "plenum", "roundtable", "negotiation", "brainstorm",
            "decision", "press_conference".

        Returns
        -------
        BasePlatform
            The instantiated platform.
        """
        name = platform_name.lower().strip()

        if name == "roundtable":
            from .platforms.roundtable import RoundtablePlatform
            return RoundtablePlatform()
        elif name == "negotiation":
            from .platforms.negotiation import NegotiationPlatform
            return NegotiationPlatform()
        elif name == "brainstorm":
            from .platforms.brainstorm import BrainstormPlatform
            return BrainstormPlatform()
        elif name == "decision":
            from .platforms.decision import DecisionPlatform
            return DecisionPlatform()
        elif name == "press_conference":
            from .platforms.press_conference import PressConferencePlatform
            return PressConferencePlatform()
        else:
            # Default: plenum (backward compatible)
            from .platforms.plenum import PlenumPlatform
            return PlenumPlatform()

    # ------------------------------------------------------------------
    # Question parsing
    # ------------------------------------------------------------------

    def _parse_question(self, question_he: str) -> dict:
        """Extract bill title, category, and target from a Hebrew question.

        Uses simple heuristics — looks for the keyword "חוק" and extracts
        surrounding context. No LLM call.

        Parameters
        ----------
        question_he : str
            The user's Hebrew question.

        Returns
        -------
        dict
            {bill_title, bill_summary, category}
        """
        bill_title = question_he[:80]
        bill_summary = question_he
        category = "כללי"

        # Try to extract a bill name: "חוק <something>"
        law_match = re.search(r"חוק\s+([^,.\n?!]{3,60})", question_he)
        if law_match:
            bill_title = f"חוק {law_match.group(1).strip()}"

        # Heuristic category detection
        category_keywords = {
            "ביטחון": ["ביטחון", "צבא", "צה\"ל", "גיוס", "טרור", "מלחמה"],
            "כלכלה": ["כלכלה", "מס", "תקציב", "שכר", "מחיר", "דיור", "נדל\"ן"],
            "חברה": ["חינוך", "בריאות", "רווחה", "ילדים", "קשישים", "נכים"],
            "דת_ומדינה": ["דת", "שבת", "כשרות", "גיור", "חרדי", "רבנות"],
            "משפט": ["בג\"ץ", "שופט", "משפט", "רפורמה", "חוקה", "בית משפט"],
            "סביבה": ["סביבה", "אקלים", "זיהום", "ירוק", "אנרגיה"],
        }

        for cat, keywords in category_keywords.items():
            for kw in keywords:
                if kw in question_he:
                    category = cat
                    break
            if category != "כללי":
                break

        return {
            "bill_title": bill_title,
            "bill_summary": bill_summary,
            "category": category,
        }

    # ------------------------------------------------------------------
    # Persona loading
    # ------------------------------------------------------------------

    def _load_personas(
        self, scenario: Optional[dict] = None,
    ) -> List[KnessetPersona]:
        """Load MK personas from RZMAPPER bridge, cache, or generate offline.

        Priority: RZMAPPER bridge > cache > graph storage > empty.

        Parameters
        ----------
        scenario : dict | None
            If scenario modifies the MK list, apply modifications.

        Returns
        -------
        list[KnessetPersona]
        """
        # Try RZMAPPER bridge first (richest data source)
        if self.rzmapper_bridge is not None:
            try:
                personas = self.rzmapper_bridge.sync_entities()
                if personas:
                    logger.info("Loaded %d personas from RZMAPPER bridge", len(personas))
                    return personas
            except Exception as e:
                logger.warning("RZMAPPER bridge persona loading failed: %s", e)

        # Try to load from cache first
        import os
        cache_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "data", "knesset_personas",
        )
        cache_dir = os.path.normpath(cache_dir)

        if os.path.isdir(cache_dir):
            personas = self._persona_generator.load_cached_personas(cache_dir)
            if personas:
                logger.info("Loaded %d personas from cache", len(personas))
                return personas

        # Generate offline from graph storage if available
        if self.graph_storage is not None:
            try:
                all_mk_nodes = self.graph_storage.list_nodes(label="MK")
                # Filter to current MKs only (25th Knesset)
                mk_nodes = [n for n in all_mk_nodes if n.get("attributes", {}).get("is_current_mk", False)]
                logger.info("Filtered: %d current MKs out of %d total", len(mk_nodes), len(all_mk_nodes))
                # Convert graph nodes to entity-like dicts for persona generator
                mk_entities = []
                for node in mk_nodes:
                    attrs = node.get("attributes", {})
                    mk_entities.append({
                        "id": node.get("id", ""),
                        "name_he": node.get("name", ""),
                        "name_en": attrs.get("name_en", ""),
                        "properties": {
                            "knesset_person_id": attrs.get("knesset_person_id", 0),
                            "party": attrs.get("party", ""),
                            "gender": attrs.get("gender", ""),
                            "is_current_mk": attrs.get("is_current_mk", False),
                            "positions": attrs.get("positions", []),
                        },
                        "influence_score": attrs.get("influence_score", 40),
                        "subtype": attrs.get("subtype", "politician"),
                    })
                logger.info("Found %d MK nodes in graph", len(mk_entities))
                if mk_entities:
                    os.makedirs(cache_dir, exist_ok=True)
                    return self._persona_generator.generate_all_personas(
                        mk_entities, cache_dir=cache_dir, use_llm=False,
                    )
            except Exception as e:
                logger.warning("Graph storage MK fetch failed: %s", e)
                import traceback
                traceback.print_exc()

        # Fallback: return empty list (simulation will be limited)
        logger.warning("No personas loaded — simulation will have no MKs")
        return []

    # ------------------------------------------------------------------
    # Coalition setup
    # ------------------------------------------------------------------

    def _setup_coalition(self) -> dict:
        """Return default 25th Knesset coalition configuration.

        Returns
        -------
        dict
            Coalition map with factions, seats, and alignment.
        """
        return dict(_DEFAULT_COALITION)

    # ------------------------------------------------------------------
    # Report generation — pure Python, no LLM
    # ------------------------------------------------------------------

    def _generate_report(self, simulation_result: dict) -> dict:
        """Generate a structured Hebrew report from simulation results.

        Pure Python analysis — no LLM call. Summarizes vote tallies per
        faction, key arguments, swing MKs, and "what would it take?"

        Parameters
        ----------
        simulation_result : dict
            Internal result with personas, parliament_state, all_actions,
            bill_outcomes, user_bill_id.

        Returns
        -------
        dict
            Structured report with sections in Hebrew.
        """
        personas: List[KnessetPersona] = simulation_result.get("personas", [])
        parliament_state: ParliamentState = simulation_result["parliament_state"]
        all_actions: List[dict] = simulation_result.get("all_actions", [])
        bill_outcomes: dict = simulation_result.get("bill_outcomes", {})
        user_bill_id: str = simulation_result.get("user_bill_id", "")

        # --- Vote tallies per faction ---
        faction_votes: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"בעד": 0, "נגד": 0, "נמנע": 0},
        )
        persona_map = {p.agent_id: p for p in personas}

        for action in all_actions:
            if action.get("action_type") == "VOTE" and action.get("bill_id") == user_bill_id:
                mk_id = action.get("agent_id", "")
                vote = action.get("vote_value", "נמנע")
                persona = persona_map.get(mk_id)
                faction = persona.faction if persona else "לא ידוע"
                if vote in faction_votes[faction]:
                    faction_votes[faction][vote] += 1

        # --- Key arguments (speeches about the user's bill) ---
        key_arguments: List[dict] = []
        for action in all_actions:
            if (
                action.get("action_type") in ("SPEAK_IN_PLENUM", "SPEAK")
                and action.get("bill_id") == user_bill_id
                and action.get("speech_text")
            ):
                key_arguments.append({
                    "mk_name": action.get("agent_name", ""),
                    "speech": action["speech_text"][:200],
                    "reasoning": action.get("reasoning", "")[:150],
                })

        # --- Swing MKs (voted differently from faction majority) ---
        # Determine faction majority per faction
        swing_mks: List[dict] = []
        for faction, tallies in faction_votes.items():
            majority_vote = max(tallies, key=tallies.get)
            # Find MKs who voted differently
            for action in all_actions:
                if (
                    action.get("action_type") == "VOTE"
                    and action.get("bill_id") == user_bill_id
                ):
                    mk_id = action.get("agent_id", "")
                    persona = persona_map.get(mk_id)
                    if persona and persona.faction == faction:
                        vote = action.get("vote_value", "")
                        if vote and vote != majority_vote:
                            swing_mks.append({
                                "mk_name": persona.name_he,
                                "faction": faction,
                                "vote": vote,
                                "faction_majority": majority_vote,
                                "reasoning": action.get("reasoning", "")[:100],
                            })

        # --- "What would it take?" analysis ---
        user_bill_outcome = bill_outcomes.get(user_bill_id, {})
        votes_for = user_bill_outcome.get("votes", {}).get("בעד", 0)
        votes_against = user_bill_outcome.get("votes", {}).get("נגד", 0)
        needed_for_majority = max(0, 61 - votes_for)

        what_it_takes = ""
        if user_bill_outcome.get("status") == "passed":
            what_it_takes = "ההצעה עברה! אין צורך בתמיכה נוספת."
        elif needed_for_majority > 0:
            what_it_takes = (
                f"נדרשים עוד {needed_for_majority} קולות בעד כדי להגיע לרוב של 61. "
                f"כרגע: {votes_for} בעד, {votes_against} נגד."
            )
        else:
            what_it_takes = f"ההצעה נכשלה עם {votes_for} בעד ו-{votes_against} נגד."

        # --- Defections ---
        defection_count = len(parliament_state.defections)

        return {
            "title_he": "סיכום סימולציית כנסת",
            "user_bill_status": user_bill_outcome.get("status", "לא ידוע"),
            "faction_vote_tallies": dict(faction_votes),
            "total_votes_for": votes_for,
            "total_votes_against": votes_against,
            "needed_for_majority": needed_for_majority,
            "what_it_takes": what_it_takes,
            "key_arguments": key_arguments[:10],
            "swing_mks": swing_mks[:10],
            "defection_count": defection_count,
            "total_bills_proposed": len(parliament_state.bills),
            "total_speeches": len(parliament_state.speeches),
        }
