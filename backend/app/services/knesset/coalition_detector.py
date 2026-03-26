"""KnessetSim — Coalition/bloc detection and power mapping.

Pure Python module (no LLM calls). Analyses voting records and persona
stances to detect blocs, compute coalition stability, find minimum
winning coalitions, and predict vote outcomes.

Usage:
    detector = CoalitionDetector(voting_analyzer=analyzer)
    blocs = detector.detect_blocs(vote_records=records)
    power_map = detector.compute_power_map(blocs, coalition_factions)
    report = detector.generate_power_report_he(power_map)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.coalition_detector")

# Hebrew vote values
VOTE_FOR = "\u05d1\u05e2\u05d3"       # בעד
VOTE_AGAINST = "\u05e0\u05d2\u05d3"    # נגד
VOTE_ABSTAIN = "\u05e0\u05de\u05e0\u05e2"  # נמנע

# Default 25th Knesset seat counts (fallback)
_DEFAULT_SEATS: Dict[str, int] = {
    "\u05dc\u05d9\u05db\u05d5\u05d3": 32,                                     # ליכוד
    "\u05d9\u05e9 \u05e2\u05ea\u05d9\u05d3": 24,                              # יש עתיד
    "\u05de\u05d7\u05e0\u05d4 \u05de\u05de\u05dc\u05db\u05ea\u05d9": 12,      # מחנה ממלכתי
    "\u05e9\"\u05e1": 11,                                                       # ש"ס
    "\u05d4\u05e6\u05d9\u05d5\u05e0\u05d5\u05ea \u05d4\u05d3\u05ea\u05d9\u05ea": 7,  # הציונות הדתית
    "\u05d9\u05d4\u05d3\u05d5\u05ea \u05d4\u05ea\u05d5\u05e8\u05d4": 7,       # יהדות התורה
    "\u05d9\u05e9\u05e8\u05d0\u05dc \u05d1\u05d9\u05ea\u05e0\u05d5": 6,       # ישראל ביתנו
    "\u05e2\u05d5\u05e6\u05de\u05d4 \u05d9\u05d4\u05d5\u05d3\u05d9\u05ea": 6, # עוצמה יהודית
    "\u05e8\u05e2\"\u05dd": 5,                                                  # רע"ם
    "\u05d4\u05e8\u05e9\u05d9\u05de\u05d4 \u05d4\u05de\u05e9\u05d5\u05ea\u05e4\u05ea": 5,  # הרשימה המשותפת
    "\u05d4\u05e2\u05d1\u05d5\u05d3\u05d4": 4,                                # העבודה
    "\u05e0\u05d5\u05e2\u05dd": 1,                                              # נועם
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Bloc:
    """A voting bloc — a group of factions that tend to vote together."""

    bloc_id: str
    label_he: str
    factions: List[str]
    total_seats: int
    cohesion_score: float  # 0-1, how unified they vote
    key_issues: List[str]  # Issues they agree on
    leader_mk_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "bloc_id": self.bloc_id,
            "label_he": self.label_he,
            "factions": self.factions,
            "total_seats": self.total_seats,
            "cohesion_score": self.cohesion_score,
            "key_issues": self.key_issues,
            "leader_mk_id": self.leader_mk_id,
        }


@dataclass
class PowerMap:
    """Full power analysis of the current Knesset configuration."""

    blocs: List[Bloc]
    coalition_strength: int  # total coalition seats
    opposition_strength: int
    swing_blocs: List[str]  # Bloc IDs that could flip the majority
    veto_players: List[str]  # Faction names whose defection breaks majority
    stability_score: float  # 0-1, how stable the current coalition is

    def to_dict(self) -> dict:
        return {
            "blocs": [b.to_dict() for b in self.blocs],
            "coalition_strength": self.coalition_strength,
            "opposition_strength": self.opposition_strength,
            "swing_blocs": self.swing_blocs,
            "veto_players": self.veto_players,
            "stability_score": self.stability_score,
        }


# ---------------------------------------------------------------------------
# CoalitionDetector
# ---------------------------------------------------------------------------

class CoalitionDetector:
    """Automatic bloc analysis and power mapping.

    Pure computation — no LLM calls.

    Parameters
    ----------
    graph_storage : Any | None
        Optional graph storage for fetching historical vote data.
    voting_analyzer : VotingPatternAnalyzer | None
        Optional voting pattern analyzer for pairwise alignment computation.
    seats_override : dict | None
        Override default seat distribution {faction_name: seat_count}.
    """

    def __init__(
        self,
        graph_storage=None,
        voting_analyzer=None,
        seats_override: Optional[Dict[str, int]] = None,
    ) -> None:
        self._graph = graph_storage
        self._voting_analyzer = voting_analyzer
        self._seats = seats_override or dict(_DEFAULT_SEATS)

    # ------------------------------------------------------------------
    # Bloc detection
    # ------------------------------------------------------------------

    def detect_blocs(
        self,
        vote_records: Optional[List[dict]] = None,
        personas: Optional[List[KnessetPersona]] = None,
    ) -> List[Bloc]:
        """Detect voting blocs from vote records or ideology alignment.

        Algorithm:
        1. Compute pairwise faction alignment (votes or stance similarity).
        2. Cluster factions by average member alignment (greedy).
        3. Label clusters by dominant ideology tags.

        Parameters
        ----------
        vote_records : list[dict] | None
            Historical vote records ``[{bill_id, mk_id, vote, faction}]``.
        personas : list[KnessetPersona] | None
            Persona list (used if vote_records unavailable).

        Returns
        -------
        list[Bloc]
        """
        if vote_records:
            return self._detect_blocs_from_votes(vote_records)
        elif personas:
            return self._detect_blocs_from_stances(personas)
        else:
            logger.warning("detect_blocs: no vote_records or personas provided")
            return []

    def _detect_blocs_from_votes(self, vote_records: List[dict]) -> List[Bloc]:
        """Cluster factions by voting alignment."""
        # Build faction vote profiles: {faction: {bill_id: majority_vote}}
        faction_votes: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int)),
        )
        faction_members: Dict[str, set] = defaultdict(set)

        for rec in vote_records:
            faction = rec.get("faction", "")
            bill_id = rec.get("bill_id", "")
            vote = rec.get("vote", "")
            mk_id = rec.get("mk_id", "")
            if faction and bill_id and vote:
                faction_votes[faction][bill_id][vote] += 1
                if mk_id:
                    faction_members[faction].add(mk_id)

        # Compute faction majority votes per bill
        faction_majority: Dict[str, Dict[str, str]] = {}
        for faction, bills in faction_votes.items():
            faction_majority[faction] = {}
            for bill_id, tallies in bills.items():
                majority = max(tallies, key=tallies.get)
                faction_majority[faction][bill_id] = majority

        # Pairwise faction alignment
        factions = list(faction_majority.keys())
        alignment: Dict[Tuple[str, str], float] = {}

        for i, f1 in enumerate(factions):
            for f2 in factions[i + 1:]:
                common_bills = set(faction_majority[f1]) & set(faction_majority[f2])
                if not common_bills:
                    alignment[(f1, f2)] = 0.0
                    continue
                agree = sum(
                    1 for b in common_bills
                    if faction_majority[f1][b] == faction_majority[f2][b]
                )
                alignment[(f1, f2)] = agree / len(common_bills)

        # Greedy clustering (threshold = 0.6 alignment)
        blocs = self._greedy_cluster(factions, alignment, threshold=0.6)
        return blocs

    def _detect_blocs_from_stances(self, personas: List[KnessetPersona]) -> List[Bloc]:
        """Cluster factions by stance similarity across personas."""
        # Average stance vector per faction
        faction_stances: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list),
        )
        stance_scale = {
            "\u05e0\u05d2\u05d3_\u05d7\u05d6\u05e7": 0.0,   # נגד_חזק
            "\u05e0\u05d2\u05d3": 0.25,                       # נגד
            "\u05e0\u05d9\u05d8\u05e8\u05dc\u05d9": 0.5,     # ניטרלי
            "\u05d1\u05e2\u05d3": 0.75,                        # בעד
            "\u05d1\u05e2\u05d3_\u05d7\u05d6\u05e7": 1.0,    # בעד_חזק
        }

        for persona in personas:
            for stance_key, stance_val in persona.stances.items():
                numeric = stance_scale.get(stance_val)
                if numeric is not None:
                    faction_stances[persona.faction][stance_key].append(numeric)

        # Average per faction per stance
        faction_avg: Dict[str, Dict[str, float]] = {}
        for faction, stances in faction_stances.items():
            faction_avg[faction] = {
                k: sum(v) / len(v) for k, v in stances.items() if v
            }

        # Pairwise alignment via cosine-like similarity
        factions = list(faction_avg.keys())
        alignment: Dict[Tuple[str, str], float] = {}

        for i, f1 in enumerate(factions):
            for f2 in factions[i + 1:]:
                common_keys = set(faction_avg[f1]) & set(faction_avg[f2])
                if not common_keys:
                    alignment[(f1, f2)] = 0.0
                    continue
                # Simple similarity: 1 - avg(abs(diff))
                diffs = [
                    abs(faction_avg[f1][k] - faction_avg[f2][k])
                    for k in common_keys
                ]
                alignment[(f1, f2)] = 1.0 - (sum(diffs) / len(diffs))

        blocs = self._greedy_cluster(factions, alignment, threshold=0.55)
        return blocs

    def _greedy_cluster(
        self,
        factions: List[str],
        alignment: Dict[Tuple[str, str], float],
        threshold: float = 0.6,
    ) -> List[Bloc]:
        """Greedy clustering of factions into blocs based on alignment scores."""
        assigned: Set[str] = set()
        blocs: List[Bloc] = []
        bloc_counter = 0

        for faction in factions:
            if faction in assigned:
                continue

            cluster = [faction]
            assigned.add(faction)

            for other in factions:
                if other in assigned:
                    continue
                # Check alignment with all current cluster members
                scores = []
                for member in cluster:
                    key = tuple(sorted([member, other]))
                    scores.append(alignment.get(key, 0.0))

                avg_score = sum(scores) / len(scores) if scores else 0.0
                if avg_score >= threshold:
                    cluster.append(other)
                    assigned.add(other)

            # Build Bloc
            total_seats = sum(self._seats.get(f, 0) for f in cluster)
            cohesion = self._compute_cluster_cohesion(cluster, alignment)

            bloc_counter += 1
            blocs.append(Bloc(
                bloc_id=f"bloc_{bloc_counter}",
                label_he=self._label_bloc(cluster),
                factions=cluster,
                total_seats=total_seats,
                cohesion_score=cohesion,
                key_issues=[],  # Could be enriched with stance data
            ))

        return blocs

    @staticmethod
    def _compute_cluster_cohesion(
        cluster: List[str],
        alignment: Dict[Tuple[str, str], float],
    ) -> float:
        """Average pairwise alignment within a cluster."""
        if len(cluster) <= 1:
            return 1.0
        scores = []
        for i, f1 in enumerate(cluster):
            for f2 in cluster[i + 1:]:
                key = tuple(sorted([f1, f2]))
                scores.append(alignment.get(key, 0.0))
        return sum(scores) / len(scores) if scores else 0.0

    @staticmethod
    def _label_bloc(factions: List[str]) -> str:
        """Generate a Hebrew label for a bloc based on its factions."""
        if len(factions) == 1:
            return factions[0]
        elif len(factions) <= 3:
            return " + ".join(factions)
        else:
            return f"{factions[0]} ועוד {len(factions) - 1}"

    # ------------------------------------------------------------------
    # Power map computation
    # ------------------------------------------------------------------

    def compute_power_map(
        self,
        blocs: List[Bloc],
        coalition_factions: List[str],
    ) -> PowerMap:
        """Analyse coalition stability and power distribution.

        Parameters
        ----------
        blocs : list[Bloc]
            Detected voting blocs.
        coalition_factions : list[str]
            Names of factions currently in the coalition.

        Returns
        -------
        PowerMap
        """
        coalition_set = set(coalition_factions)
        coalition_seats = sum(self._seats.get(f, 0) for f in coalition_factions)
        total_seats = sum(self._seats.values())
        opposition_seats = total_seats - coalition_seats

        # Find swing blocs: blocs containing coalition factions
        # whose removal drops below 61
        swing_blocs: List[str] = []
        for bloc in blocs:
            coalition_members_in_bloc = [
                f for f in bloc.factions if f in coalition_set
            ]
            if not coalition_members_in_bloc:
                continue
            bloc_coalition_seats = sum(
                self._seats.get(f, 0) for f in coalition_members_in_bloc
            )
            if coalition_seats - bloc_coalition_seats < 61:
                swing_blocs.append(bloc.bloc_id)

        # Veto players: individual factions whose exit breaks majority
        veto_players: List[str] = []
        for faction in coalition_factions:
            seats = self._seats.get(faction, 0)
            if coalition_seats - seats < 61:
                veto_players.append(faction)

        # Stability score: based on margin above 61 and cohesion
        margin = max(0, coalition_seats - 61)
        margin_factor = min(1.0, margin / 10.0)  # 10+ seat margin = 1.0

        coalition_blocs = [
            b for b in blocs
            if any(f in coalition_set for f in b.factions)
        ]
        avg_cohesion = (
            sum(b.cohesion_score for b in coalition_blocs) / len(coalition_blocs)
            if coalition_blocs else 0.5
        )

        veto_factor = max(0.0, 1.0 - len(veto_players) * 0.15)

        stability = round(
            0.4 * margin_factor + 0.35 * avg_cohesion + 0.25 * veto_factor,
            3,
        )

        return PowerMap(
            blocs=blocs,
            coalition_strength=coalition_seats,
            opposition_strength=opposition_seats,
            swing_blocs=swing_blocs,
            veto_players=veto_players,
            stability_score=stability,
        )

    # ------------------------------------------------------------------
    # Minimum winning coalitions
    # ------------------------------------------------------------------

    def find_minimum_winning_coalition(
        self,
        blocs: List[Bloc],
        required_seats: int = 61,
    ) -> List[List[str]]:
        """Find all possible coalitions that reach the required seats.

        Sorted by fewest factions (more stable coalitions first).

        Parameters
        ----------
        blocs : list[Bloc]
            Available voting blocs.
        required_seats : int
            Seats needed for majority (default 61).

        Returns
        -------
        list[list[str]]
            Possible faction combinations, each sorted by name.
        """
        # Work at faction level for granularity
        all_factions = list(self._seats.keys())
        winning: List[Tuple[int, List[str]]] = []

        # Try combinations of increasing size (2..n)
        max_size = min(len(all_factions), 8)  # cap to avoid combinatorial explosion
        for size in range(2, max_size + 1):
            for combo in combinations(all_factions, size):
                total = sum(self._seats.get(f, 0) for f in combo)
                if total >= required_seats:
                    # Check it's minimal: removing any faction drops below threshold
                    is_minimal = all(
                        total - self._seats.get(f, 0) < required_seats
                        for f in combo
                    )
                    if is_minimal:
                        winning.append((size, sorted(combo)))

            # Stop after finding solutions at this size (fewest factions wins)
            if winning:
                break

        # Sort by number of factions, then total seats (fewer seats = tighter)
        winning.sort(key=lambda x: (x[0], sum(self._seats.get(f, 0) for f in x[1])))
        return [combo for _, combo in winning[:20]]  # cap at 20 results

    # ------------------------------------------------------------------
    # Vote prediction
    # ------------------------------------------------------------------

    def predict_vote_outcome(
        self,
        bill_topic: str,
        personas: List[KnessetPersona],
        blocs: List[Bloc],
    ) -> dict:
        """Predict vote outcome based on bloc stances.

        Maps the bill topic to stance keys and sums predicted votes
        per bloc.

        Parameters
        ----------
        bill_topic : str
            Topic/category of the bill (from orchestrator._parse_question).
        personas : list[KnessetPersona]
            All MK personas.
        blocs : list[Bloc]
            Detected blocs.

        Returns
        -------
        dict
            {predicted_for, predicted_against, predicted_abstain,
             bloc_breakdown, confidence, swing_analysis}
        """
        # Map topics to stance keys
        topic_stance_map: Dict[str, List[str]] = {
            "\u05d1\u05d9\u05d8\u05d7\u05d5\u05df": ["\u05d1\u05d9\u05d8\u05d7\u05d5\u05df_\u05dc\u05d0\u05d5\u05de\u05d9"],  # ביטחון
            "\u05db\u05dc\u05db\u05dc\u05d4": ["\u05db\u05dc\u05db\u05dc\u05d4"],  # כלכלה
            "\u05d3\u05ea_\u05d5\u05de\u05d3\u05d9\u05e0\u05d4": ["\u05d3\u05ea_\u05d5\u05de\u05d3\u05d9\u05e0\u05d4"],  # דת_ומדינה
            "\u05de\u05e9\u05e4\u05d8": ["\u05e8\u05e4\u05d5\u05e8\u05de\u05d4_\u05de\u05e9\u05e4\u05d8\u05d9\u05ea"],  # משפט
            "\u05d7\u05d1\u05e8\u05d4": ["\u05d6\u05db\u05d5\u05d9\u05d5\u05ea_\u05de\u05d9\u05e2\u05d5\u05d8\u05d9\u05dd"],  # חברה
            "\u05e1\u05d1\u05d9\u05d1\u05d4": ["\u05e1\u05d1\u05d9\u05d1\u05d4"],  # סביבה
        }

        stance_keys = topic_stance_map.get(bill_topic, [])

        # If no stance mapping, use faction-based heuristic
        predicted_for = 0
        predicted_against = 0
        predicted_abstain = 0
        bloc_breakdown: List[dict] = []
        total_counted = 0

        persona_by_faction: Dict[str, List[KnessetPersona]] = defaultdict(list)
        for p in personas:
            persona_by_faction[p.faction].append(p)

        for bloc in blocs:
            bloc_for = 0
            bloc_against = 0
            bloc_abstain = 0

            for faction in bloc.factions:
                faction_personas = persona_by_faction.get(faction, [])
                for persona in faction_personas:
                    vote = self._predict_mk_vote(persona, stance_keys)
                    if vote == VOTE_FOR:
                        bloc_for += 1
                    elif vote == VOTE_AGAINST:
                        bloc_against += 1
                    else:
                        bloc_abstain += 1
                    total_counted += 1

            predicted_for += bloc_for
            predicted_against += bloc_against
            predicted_abstain += bloc_abstain

            bloc_breakdown.append({
                "bloc_id": bloc.bloc_id,
                "label_he": bloc.label_he,
                "for": bloc_for,
                "against": bloc_against,
                "abstain": bloc_abstain,
            })

        # Confidence based on how many personas had clear stance data
        confidence = min(1.0, total_counted / max(len(personas), 1))

        # Swing analysis
        swing_analysis = ""
        gap = abs(predicted_for - predicted_against)
        if gap <= 5:
            swing_analysis = f"ההצבעה צפויה להיות צמודה (פער של {gap} קולות). כל ח\"כ נדנדה יכול להכריע."
        elif predicted_for >= 61:
            swing_analysis = f"ההצעה צפויה לעבור ברוב של {predicted_for} קולות."
        else:
            needed = 61 - predicted_for
            swing_analysis = f"ההצעה צפויה ליפול. נדרשים עוד {needed} קולות בעד."

        return {
            "predicted_for": predicted_for,
            "predicted_against": predicted_against,
            "predicted_abstain": predicted_abstain,
            "bloc_breakdown": bloc_breakdown,
            "confidence": round(confidence, 2),
            "swing_analysis": swing_analysis,
        }

    @staticmethod
    def _predict_mk_vote(
        persona: KnessetPersona, stance_keys: List[str],
    ) -> str:
        """Predict a single MK's vote based on their stances."""
        if not stance_keys:
            # No stance mapping — use coalition heuristic
            return VOTE_FOR if persona.coalition_member else VOTE_AGAINST

        pro_stances = {"\u05d1\u05e2\u05d3", "\u05d1\u05e2\u05d3_\u05d7\u05d6\u05e7"}
        anti_stances = {"\u05e0\u05d2\u05d3", "\u05e0\u05d2\u05d3_\u05d7\u05d6\u05e7"}

        pro_count = 0
        anti_count = 0
        for key in stance_keys:
            stance_val = persona.stances.get(key, "")
            if stance_val in pro_stances:
                pro_count += 1
            elif stance_val in anti_stances:
                anti_count += 1

        if pro_count > anti_count:
            return VOTE_FOR
        elif anti_count > pro_count:
            return VOTE_AGAINST
        else:
            return VOTE_ABSTAIN

    # ------------------------------------------------------------------
    # Faction split detection
    # ------------------------------------------------------------------

    def detect_faction_splits(
        self,
        vote_records: List[dict],
        faction_members: Dict[str, List[str]],
    ) -> List[dict]:
        """Find factions with internal disagreement.

        Parameters
        ----------
        vote_records : list[dict]
            Vote records ``[{bill_id, mk_id, vote, faction}]``.
        faction_members : dict
            ``{faction_name: [mk_id, ...]}``

        Returns
        -------
        list[dict]
            ``[{faction, cohesion, dissidents: [mk_ids], split_issues}]``
        """
        # Build per-faction per-bill vote tallies
        faction_bill_votes: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int)),
        )
        mk_votes: Dict[str, Dict[str, str]] = defaultdict(dict)

        for rec in vote_records:
            faction = rec.get("faction", "")
            bill_id = rec.get("bill_id", "")
            vote = rec.get("vote", "")
            mk_id = rec.get("mk_id", "")
            if faction and bill_id and vote:
                faction_bill_votes[faction][bill_id][vote] += 1
                if mk_id:
                    mk_votes[mk_id][bill_id] = vote

        results: List[dict] = []

        for faction, members in faction_members.items():
            if not members:
                continue

            bills = faction_bill_votes.get(faction, {})
            if not bills:
                continue

            total_votes = 0
            dissenting_votes = 0
            dissidents: Set[str] = set()
            split_issues: List[str] = []

            for bill_id, tallies in bills.items():
                if not tallies:
                    continue
                majority_vote = max(tallies, key=tallies.get)
                bill_total = sum(tallies.values())
                bill_dissent = bill_total - tallies[majority_vote]
                total_votes += bill_total
                dissenting_votes += bill_dissent

                # Track which members dissented
                if bill_dissent > 0:
                    split_issues.append(bill_id)
                    for mk_id in members:
                        mk_vote = mk_votes.get(mk_id, {}).get(bill_id)
                        if mk_vote and mk_vote != majority_vote:
                            dissidents.add(mk_id)

            cohesion = 1.0 - (dissenting_votes / total_votes) if total_votes > 0 else 1.0

            if dissidents:
                results.append({
                    "faction": faction,
                    "cohesion": round(cohesion, 3),
                    "dissidents": sorted(dissidents),
                    "split_issues": split_issues[:10],
                    "total_votes_analysed": total_votes,
                })

        # Sort by lowest cohesion (most split first)
        results.sort(key=lambda x: x["cohesion"])
        return results

    # ------------------------------------------------------------------
    # Hebrew report generation
    # ------------------------------------------------------------------

    def generate_power_report_he(self, power_map: PowerMap) -> str:
        """Generate a Hebrew power analysis report.

        Parameters
        ----------
        power_map : PowerMap
            Computed power map.

        Returns
        -------
        str
            Multi-line Hebrew text report.
        """
        lines: List[str] = []
        lines.append("=== \u05de\u05e4\u05ea \u05db\u05d5\u05d7 \u05e4\u05d5\u05dc\u05d9\u05d8\u05d9\u05ea ===")  # מפת כוח פוליטית

        # Coalition vs opposition
        lines.append(
            f"\u05d4\u05e7\u05d5\u05d0\u05dc\u05d9\u05e6\u05d9\u05d4 \u05de\u05d7\u05d6\u05d9\u05e7\u05d4 "  # הקואליציה מחזיקה
            f"{power_map.coalition_strength} \u05de\u05e0\u05d3\u05d8\u05d9\u05dd "  # מנדטים
            f"\u05de\u05d5\u05dc {power_map.opposition_strength} "  # מול
            f"\u05d1\u05d0\u05d5\u05e4\u05d5\u05d6\u05d9\u05e6\u05d9\u05d4."  # באופוזיציה.
        )

        margin = power_map.coalition_strength - 61
        if margin > 0:
            lines.append(f"\u05e8\u05d5\u05d1 \u05e9\u05dc {margin} \u05de\u05e2\u05dc 61.")  # רוב של X מעל 61.
        elif margin == 0:
            lines.append("\u05e8\u05d5\u05d1 \u05de\u05d9\u05e0\u05d9\u05de\u05dc\u05d9 \u05d1\u05d3\u05d9\u05d5\u05e7 \u2014 61 \u05de\u05e0\u05d3\u05d8\u05d9\u05dd.")  # רוב מינימלי בדיוק
        else:
            lines.append(f"\u05d0\u05d9\u05df \u05e8\u05d5\u05d1! \u05d7\u05e1\u05e8\u05d9\u05dd {abs(margin)} \u05de\u05e0\u05d3\u05d8\u05d9\u05dd.")  # אין רוב! חסרים X

        lines.append("")

        # Stability
        stability_pct = int(power_map.stability_score * 100)
        if stability_pct >= 70:
            stability_desc = "\u05d9\u05e6\u05d9\u05d1\u05d4"  # יציבה
        elif stability_pct >= 40:
            stability_desc = "\u05d1\u05d9\u05e0\u05d5\u05e0\u05d9\u05ea"  # בינונית
        else:
            stability_desc = "\u05e9\u05d1\u05e8\u05d9\u05e8\u05d9\u05ea"  # שברירית
        lines.append(f"\u05d9\u05e6\u05d9\u05d1\u05d5\u05ea: {stability_pct}% ({stability_desc})")  # יציבות

        # Veto players
        if power_map.veto_players:
            lines.append("")
            lines.append("\u05e9\u05d7\u05e7\u05e0\u05d9 \u05d5\u05d8\u05d5 (\u05e4\u05e8\u05d9\u05e9\u05ea\u05dd \u05e9\u05d5\u05d1\u05e8\u05ea \u05e8\u05d5\u05d1):")  # שחקני וטו (פרישתם שוברת רוב):
            for vp in power_map.veto_players:
                seats = self._seats.get(vp, 0)
                lines.append(f"  - {vp} ({seats} \u05de\u05e0\u05d3\u05d8\u05d9\u05dd)")  # מנדטים

        # Blocs
        if power_map.blocs:
            lines.append("")
            lines.append("\u05d2\u05d5\u05e9\u05d9\u05dd \u05e4\u05d5\u05dc\u05d9\u05d8\u05d9\u05d9\u05dd:")  # גושים פוליטיים:
            for bloc in power_map.blocs:
                cohesion_pct = int(bloc.cohesion_score * 100)
                lines.append(
                    f"  {bloc.label_he}: {bloc.total_seats} \u05de\u05e0\u05d3\u05d8\u05d9\u05dd "
                    f"(\u05dc\u05db\u05d9\u05d3\u05d5\u05ea {cohesion_pct}%)"  # לכידות
                )

        # Swing blocs
        if power_map.swing_blocs:
            lines.append("")
            lines.append("\u05d2\u05d5\u05e9\u05d9 \u05e0\u05d3\u05e0\u05d3\u05d4 (\u05d9\u05db\u05d5\u05dc\u05d9\u05dd \u05dc\u05d4\u05e4\u05d5\u05da \u05e8\u05d5\u05d1):")  # גושי נדנדה (יכולים להפוך רוב):
            for bloc_id in power_map.swing_blocs:
                bloc = next((b for b in power_map.blocs if b.bloc_id == bloc_id), None)
                if bloc:
                    lines.append(f"  - {bloc.label_he} ({bloc.total_seats} \u05de\u05e0\u05d3\u05d8\u05d9\u05dd)")

        return "\n".join(lines)
