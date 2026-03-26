"""KnessetScenarioEngine — what-if scenario modifiers for KnessetSim.

Supports election changes, MK defections, crisis events, and coalition
collapses. Each scenario mutates the persona list and/or coalition map
before the simulation loop runs.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Tuple

from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.scenarios")

# ---------------------------------------------------------------------------
# Crisis stance-shift rules
# ---------------------------------------------------------------------------

# Maps crisis type -> (stance_field, shift_direction)
# shift_direction: +1 = hawkish/stronger, -1 = dovish/weaker
_STANCE_SCALE = ["נגד_חזק", "נגד", "ניטרלי", "בעד", "בעד_חזק"]

_CRISIS_SHIFTS: Dict[str, List[Tuple[str, int]]] = {
    "security": [
        ("ביטחון_לאומי", +1),
        ("תקציב_ביטחון", +1),
        ("שני_מדינות", -1),
    ],
    "economic": [
        ("כלכלה", -1),  # shift toward social/interventionist
        ("תקציב_ביטחון", -1),
    ],
    "social": [
        ("זכויות_מיעוטים", +1),
        ("דת_ומדינה", -1),  # shift toward secular
    ],
}


def _shift_stance(current: str, direction: int) -> str:
    """Shift a stance value along the scale by direction steps.

    Parameters
    ----------
    current : str
        Current stance value (e.g., "בעד", "ניטרלי").
    direction : int
        +1 to shift hawkish/stronger, -1 to shift dovish/weaker.

    Returns
    -------
    str
        New stance value, clamped to scale bounds.
    """
    if current not in _STANCE_SCALE:
        return current
    idx = _STANCE_SCALE.index(current)
    new_idx = max(0, min(len(_STANCE_SCALE) - 1, idx + direction))
    return _STANCE_SCALE[new_idx]


class KnessetScenarioEngine:
    """What-if scenario engine for KnessetSim.

    Modifies persona lists and coalition maps before the simulation
    loop runs, enabling counterfactual analysis.
    """

    def apply_scenario(
        self,
        scenario_type: str,
        params: dict,
        personas: List[KnessetPersona],
        coalition_map: Dict[str, str],
    ) -> Tuple[List[KnessetPersona], Dict[str, str]]:
        """Apply a scenario modification to personas and coalition map.

        Parameters
        ----------
        scenario_type : str
            One of: "election_change", "mk_defection", "crisis_event",
            "coalition_collapse".
        params : dict
            Scenario-specific parameters (see individual handlers).
        personas : list[KnessetPersona]
            Current persona list (will be deep-copied before mutation).
        coalition_map : dict
            Current coalition map {faction: "coalition"|"opposition"}.

        Returns
        -------
        tuple[list[KnessetPersona], dict]
            Modified (personas, coalition_map).
        """
        # Deep copy to avoid mutating originals
        personas = [copy.deepcopy(p) for p in personas]
        coalition_map = dict(coalition_map)

        handler = {
            "election_change": self._election_change,
            "mk_defection": self._mk_defection,
            "crisis_event": self._crisis_event,
            "coalition_collapse": self._coalition_collapse,
        }.get(scenario_type)

        if handler is None:
            logger.warning("Unknown scenario type: %s", scenario_type)
            return personas, coalition_map

        logger.info("Applying scenario: %s with params: %s", scenario_type, params)
        return handler(params, personas, coalition_map)

    # ------------------------------------------------------------------
    # Scenario handlers
    # ------------------------------------------------------------------

    def _election_change(
        self,
        params: dict,
        personas: List[KnessetPersona],
        coalition_map: Dict[str, str],
    ) -> Tuple[List[KnessetPersona], Dict[str, str]]:
        """Reconfigure coalition based on new election results.

        Parameters
        ----------
        params : dict
            {
                "winning_party": str,  # party that forms coalition
                "seats": {party: count},  # new seat distribution
                "new_coalition": [str],  # list of coalition faction names
            }

        Returns
        -------
        tuple[list[KnessetPersona], dict]
        """
        seats = params.get("seats", {})
        new_coalition_factions = params.get("new_coalition", [])
        winning_party = params.get("winning_party", "")

        if not new_coalition_factions and winning_party:
            # Default: winning party + its natural allies form coalition
            new_coalition_factions = [winning_party]

        # Rebuild coalition map
        new_coalition_map: Dict[str, str] = {}
        coalition_set = set(new_coalition_factions)

        all_factions = set(coalition_map.keys())
        for faction in seats:
            all_factions.add(faction)

        for faction in all_factions:
            if faction in coalition_set:
                new_coalition_map[faction] = "coalition"
            else:
                new_coalition_map[faction] = "opposition"

        # Update personas' coalition_member flag
        for persona in personas:
            persona.coalition_member = persona.faction in coalition_set

        logger.info(
            "Election change: coalition=%s, winning=%s",
            new_coalition_factions, winning_party,
        )

        return personas, new_coalition_map

    def _mk_defection(
        self,
        params: dict,
        personas: List[KnessetPersona],
        coalition_map: Dict[str, str],
    ) -> Tuple[List[KnessetPersona], Dict[str, str]]:
        """Move an MK between factions.

        Parameters
        ----------
        params : dict
            {
                "mk_id": str,
                "from_faction": str,
                "to_faction": str,
            }

        Returns
        -------
        tuple[list[KnessetPersona], dict]
        """
        mk_id = params.get("mk_id", "")
        from_faction = params.get("from_faction", "")
        to_faction = params.get("to_faction", "")

        if not mk_id or not to_faction:
            logger.warning("mk_defection: missing mk_id or to_faction")
            return personas, coalition_map

        for persona in personas:
            if persona.agent_id == mk_id:
                old_faction = persona.faction
                persona.faction = to_faction
                # Update coalition membership based on new faction
                new_role = coalition_map.get(to_faction, "opposition")
                persona.coalition_member = (new_role == "coalition")
                # Defecting lowers loyalty
                persona.loyalty_score = max(0.1, persona.loyalty_score - 0.3)

                logger.info(
                    "MK defection: %s (%s) %s -> %s",
                    persona.name_he, mk_id, old_faction, to_faction,
                )
                break
        else:
            logger.warning("mk_defection: MK %s not found", mk_id)

        return personas, coalition_map

    def _crisis_event(
        self,
        params: dict,
        personas: List[KnessetPersona],
        coalition_map: Dict[str, str],
    ) -> Tuple[List[KnessetPersona], Dict[str, str]]:
        """Shift MK stances based on a crisis type.

        Parameters
        ----------
        params : dict
            {
                "event_type": "security" | "economic" | "social",
                "description_he": str,
            }

        Returns
        -------
        tuple[list[KnessetPersona], dict]
        """
        event_type = params.get("event_type", "")
        description = params.get("description_he", "")

        shifts = _CRISIS_SHIFTS.get(event_type)
        if not shifts:
            logger.warning("crisis_event: unknown event_type '%s'", event_type)
            return personas, coalition_map

        shifted_count = 0
        for persona in personas:
            for stance_field, direction in shifts:
                current = persona.stances.get(stance_field)
                if current:
                    new_val = _shift_stance(current, direction)
                    if new_val != current:
                        persona.stances[stance_field] = new_val
                        shifted_count += 1

        logger.info(
            "Crisis event '%s': shifted %d stance values across %d MKs. %s",
            event_type, shifted_count, len(personas), description[:80],
        )

        return personas, coalition_map

    def _coalition_collapse(
        self,
        params: dict,
        personas: List[KnessetPersona],
        coalition_map: Dict[str, str],
    ) -> Tuple[List[KnessetPersona], Dict[str, str]]:
        """One faction leaves the coalition. Recalculate majority.

        Parameters
        ----------
        params : dict
            {
                "leaving_faction": str,  # faction that leaves
            }

        Returns
        -------
        tuple[list[KnessetPersona], dict]
        """
        leaving = params.get("leaving_faction", "")
        if not leaving:
            logger.warning("coalition_collapse: no leaving_faction specified")
            return personas, coalition_map

        if coalition_map.get(leaving) != "coalition":
            logger.warning(
                "coalition_collapse: %s is not in coalition (current: %s)",
                leaving, coalition_map.get(leaving),
            )
            return personas, coalition_map

        # Move faction to opposition
        coalition_map[leaving] = "opposition"

        # Update personas
        for persona in personas:
            if persona.faction == leaving:
                persona.coalition_member = False

        # Count remaining coalition seats
        remaining_coalition = [
            f for f, role in coalition_map.items() if role == "coalition"
        ]

        logger.info(
            "Coalition collapse: %s left. Remaining coalition: %s",
            leaving, remaining_coalition,
        )

        return personas, coalition_map
