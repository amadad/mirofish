"""KnessetSim Phase 3 — Voting pattern analysis.

Pure Python module (no LLM calls). Computes MK alignment scores,
faction cohesion, coalition loyalty, swing voter detection, and
voting-based clustering.

All vote_records are expected as List[dict] where each dict has:
    bill_id, mk_id, mk_name, vote ("בעד" | "נגד" | "נמנע"), faction
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("mirofish.knesset.voting_patterns")

# Hebrew vote values (from types.py VoteValue)
VOTE_FOR = "\u05d1\u05e2\u05d3"       # בעד
VOTE_AGAINST = "\u05e0\u05d2\u05d3"    # נגד
VOTE_ABSTAIN = "\u05e0\u05de\u05e0\u05e2"  # נמנע


class VotingPatternAnalyzer:
    """Analyze Knesset voting patterns — pure computation, no LLM calls."""

    def __init__(self, graph_storage=None):
        """
        Args:
            graph_storage: Optional GraphStorage for fetching vote data.
                           Methods also accept vote_records directly.
        """
        self._graph = graph_storage

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_mk_vote_map(
        vote_records: List[dict],
    ) -> Dict[str, Dict[str, str]]:
        """Build {mk_id: {bill_id: vote_value}} from flat records."""
        result: Dict[str, Dict[str, str]] = defaultdict(dict)
        for rec in vote_records:
            mk_id = rec.get("mk_id", "")
            bill_id = rec.get("bill_id", "")
            vote = rec.get("vote", "")
            if mk_id and bill_id and vote:
                result[mk_id][bill_id] = vote
        return dict(result)

    @staticmethod
    def _shared_bills(
        votes_a: Dict[str, str],
        votes_b: Dict[str, str],
    ) -> Set[str]:
        """Bills where both MKs cast a vote (not abstain)."""
        active_votes = {VOTE_FOR, VOTE_AGAINST}
        bills_a = {b for b, v in votes_a.items() if v in active_votes}
        bills_b = {b for b, v in votes_b.items() if v in active_votes}
        return bills_a & bills_b

    # ------------------------------------------------------------------
    # 1. MK-to-MK alignment
    # ------------------------------------------------------------------

    def compute_mk_alignment(
        self,
        mk_id_a: str,
        mk_id_b: str,
        vote_records: List[dict],
    ) -> float:
        """Compute 0-1 alignment score between two MKs.

        Only considers bills where both MKs voted (for or against).
        Abstentions are excluded from the calculation.

        Returns:
            Float 0.0 (always disagree) to 1.0 (always agree).
            Returns 0.0 if no shared votes exist.
        """
        mk_votes = self._build_mk_vote_map(vote_records)
        votes_a = mk_votes.get(mk_id_a, {})
        votes_b = mk_votes.get(mk_id_b, {})

        shared = self._shared_bills(votes_a, votes_b)
        if not shared:
            return 0.0

        agree = sum(1 for b in shared if votes_a[b] == votes_b[b])
        return agree / len(shared)

    # ------------------------------------------------------------------
    # 2. Faction cohesion
    # ------------------------------------------------------------------

    def compute_faction_cohesion(
        self,
        faction_members: List[str],
        vote_records: List[dict],
    ) -> float:
        """Compute average pairwise alignment within a faction.

        Returns:
            Float 0.0 to 1.0 (1.0 = all members always vote together).
            Returns 0.0 if fewer than 2 members.
        """
        if len(faction_members) < 2:
            return 0.0

        total = 0.0
        pairs = 0
        for i in range(len(faction_members)):
            for j in range(i + 1, len(faction_members)):
                score = self.compute_mk_alignment(
                    faction_members[i], faction_members[j], vote_records
                )
                total += score
                pairs += 1

        return total / pairs if pairs > 0 else 0.0

    # ------------------------------------------------------------------
    # 3. Coalition loyalty
    # ------------------------------------------------------------------

    def compute_coalition_loyalty(
        self,
        mk_id: str,
        coalition_factions: List[str],
        vote_records: List[dict],
    ) -> float:
        """How often an MK votes with the coalition majority.

        For each bill, determines the coalition majority vote,
        then checks if the MK voted the same way.

        Returns:
            Float 0.0 to 1.0 (1.0 = always votes with coalition).
        """
        mk_votes = self._build_mk_vote_map(vote_records)
        target_votes = mk_votes.get(mk_id, {})
        if not target_votes:
            return 0.0

        # Build faction lookup: mk_id -> faction
        mk_factions: Dict[str, str] = {}
        for rec in vote_records:
            mid = rec.get("mk_id", "")
            fac = rec.get("faction", "")
            if mid and fac:
                mk_factions[mid] = fac

        # Coalition member IDs
        coalition_mks = {
            mid for mid, fac in mk_factions.items()
            if fac in coalition_factions
        }

        # For each bill, find coalition majority vote
        bills_with_votes: Dict[str, List[str]] = defaultdict(list)
        for rec in vote_records:
            if rec.get("mk_id") in coalition_mks:
                bill_id = rec.get("bill_id", "")
                vote = rec.get("vote", "")
                if bill_id and vote in (VOTE_FOR, VOTE_AGAINST):
                    bills_with_votes[bill_id].append(vote)

        aligned = 0
        total = 0
        for bill_id, my_vote in target_votes.items():
            if my_vote not in (VOTE_FOR, VOTE_AGAINST):
                continue
            coalition_votes = bills_with_votes.get(bill_id, [])
            if not coalition_votes:
                continue
            # Majority: most common vote among coalition members
            for_count = coalition_votes.count(VOTE_FOR)
            against_count = coalition_votes.count(VOTE_AGAINST)
            majority = VOTE_FOR if for_count >= against_count else VOTE_AGAINST
            total += 1
            if my_vote == majority:
                aligned += 1

        return aligned / total if total > 0 else 0.0

    # ------------------------------------------------------------------
    # 4. Swing voters
    # ------------------------------------------------------------------

    def find_swing_voters(
        self,
        vote_records: List[dict],
        coalition_factions: List[str],
    ) -> List[dict]:
        """Find MKs who vote against their faction/coalition most often.

        Returns:
            List of dicts sorted by defection_rate descending:
                [{mk_id, mk_name, defection_rate, faction}]
        """
        # Build faction lookup
        mk_meta: Dict[str, dict] = {}
        for rec in vote_records:
            mid = rec.get("mk_id", "")
            if mid and mid not in mk_meta:
                mk_meta[mid] = {
                    "mk_name": rec.get("mk_name", ""),
                    "faction": rec.get("faction", ""),
                }

        # Compute faction majority per bill
        faction_bill_votes: Dict[str, Dict[str, List[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for rec in vote_records:
            fac = rec.get("faction", "")
            bill_id = rec.get("bill_id", "")
            vote = rec.get("vote", "")
            if fac and bill_id and vote in (VOTE_FOR, VOTE_AGAINST):
                faction_bill_votes[fac][bill_id].append(vote)

        # For each MK, count defections from their faction majority
        mk_votes = self._build_mk_vote_map(vote_records)
        swing: List[dict] = []

        for mk_id, meta in mk_meta.items():
            faction = meta["faction"]
            if not faction:
                continue
            my_votes = mk_votes.get(mk_id, {})
            defections = 0
            total = 0

            for bill_id, my_vote in my_votes.items():
                if my_vote not in (VOTE_FOR, VOTE_AGAINST):
                    continue
                fac_votes = faction_bill_votes.get(faction, {}).get(bill_id, [])
                if not fac_votes:
                    continue
                for_count = fac_votes.count(VOTE_FOR)
                against_count = fac_votes.count(VOTE_AGAINST)
                majority = VOTE_FOR if for_count >= against_count else VOTE_AGAINST
                total += 1
                if my_vote != majority:
                    defections += 1

            if total > 0:
                rate = defections / total
                swing.append({
                    "mk_id": mk_id,
                    "mk_name": meta["mk_name"],
                    "defection_rate": round(rate, 4),
                    "faction": faction,
                })

        swing.sort(key=lambda x: x["defection_rate"], reverse=True)
        return swing

    # ------------------------------------------------------------------
    # 5. Voting-based clustering
    # ------------------------------------------------------------------

    def cluster_by_voting(
        self,
        vote_records: List[dict],
        mk_ids: List[str],
        threshold: float = 0.7,
    ) -> Dict[str, List[str]]:
        """Group MKs by voting similarity using simple clustering.

        Two MKs are in the same cluster if their alignment >= threshold.
        Uses greedy single-linkage: iterate MKs, assign to first matching
        cluster, or start a new one.

        Args:
            vote_records: Flat vote records.
            mk_ids: MK IDs to cluster.
            threshold: Minimum alignment to join a cluster (default 0.7).

        Returns:
            {cluster_label: [mk_ids]} where labels are "cluster_0", etc.
        """
        if not mk_ids:
            return {}

        # Pre-compute pairwise alignment matrix (lazy — only as needed)
        mk_votes = self._build_mk_vote_map(vote_records)
        alignment_cache: Dict[Tuple[str, str], float] = {}

        def get_alignment(a: str, b: str) -> float:
            key = (min(a, b), max(a, b))
            if key not in alignment_cache:
                alignment_cache[key] = self.compute_mk_alignment(
                    a, b, vote_records
                )
            return alignment_cache[key]

        clusters: List[List[str]] = []

        for mk_id in mk_ids:
            if mk_id not in mk_votes:
                continue

            placed = False
            for cluster in clusters:
                # Check alignment with first member (representative)
                if get_alignment(mk_id, cluster[0]) >= threshold:
                    cluster.append(mk_id)
                    placed = True
                    break

            if not placed:
                clusters.append([mk_id])

        return {
            f"cluster_{i}": members
            for i, members in enumerate(clusters)
        }

    # ------------------------------------------------------------------
    # 6. MK voting profile
    # ------------------------------------------------------------------

    def get_mk_voting_profile(
        self,
        mk_id: str,
        vote_records: List[dict],
        coalition_factions: Optional[List[str]] = None,
    ) -> dict:
        """Build a comprehensive voting profile for a single MK.

        Returns:
            {
                total_votes, for_pct, against_pct, abstain_pct,
                coalition_alignment, top_allies, top_rivals
            }
        """
        mk_votes = self._build_mk_vote_map(vote_records)
        my_votes = mk_votes.get(mk_id, {})

        if not my_votes:
            return {
                "total_votes": 0,
                "for_pct": 0.0,
                "against_pct": 0.0,
                "abstain_pct": 0.0,
                "coalition_alignment": 0.0,
                "top_allies": [],
                "top_rivals": [],
            }

        total = len(my_votes)
        for_count = sum(1 for v in my_votes.values() if v == VOTE_FOR)
        against_count = sum(1 for v in my_votes.values() if v == VOTE_AGAINST)
        abstain_count = sum(1 for v in my_votes.values() if v == VOTE_ABSTAIN)

        # Coalition alignment
        coal_align = 0.0
        if coalition_factions:
            coal_align = self.compute_coalition_loyalty(
                mk_id, coalition_factions, vote_records
            )

        # Top allies and rivals: alignment with all other MKs
        all_mk_ids = [mid for mid in mk_votes if mid != mk_id]
        alignments: List[Tuple[str, float]] = []
        for other_id in all_mk_ids:
            score = self.compute_mk_alignment(mk_id, other_id, vote_records)
            alignments.append((other_id, score))

        alignments.sort(key=lambda x: x[1], reverse=True)

        # Resolve names
        mk_names: Dict[str, str] = {}
        for rec in vote_records:
            mid = rec.get("mk_id", "")
            name = rec.get("mk_name", "")
            if mid and name:
                mk_names[mid] = name

        top_allies = [
            {"mk_id": mid, "mk_name": mk_names.get(mid, mid), "alignment": round(s, 4)}
            for mid, s in alignments[:5]
        ]
        top_rivals = [
            {"mk_id": mid, "mk_name": mk_names.get(mid, mid), "alignment": round(s, 4)}
            for mid, s in alignments[-5:]
        ]

        return {
            "total_votes": total,
            "for_pct": round(for_count / total, 4) if total else 0.0,
            "against_pct": round(against_count / total, 4) if total else 0.0,
            "abstain_pct": round(abstain_count / total, 4) if total else 0.0,
            "coalition_alignment": round(coal_align, 4),
            "top_allies": top_allies,
            "top_rivals": top_rivals,
        }
