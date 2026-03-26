"""KnessetSim — Scenario branching for fork-and-compare simulations.

Allows users to clone a base simulation, apply a diff (e.g., flip one MK's
vote, remove a faction from the coalition), run the branch, and compare
outcomes side-by-side.

Usage:
    brancher = ScenarioBrancher(orchestrator)
    branch = await brancher.create_branch(base_sim_id, "ליברמן מצביע נגד", diff)
    results = await brancher.run_branches(base_sim_id, question_he, rounds=5)
    comparison = brancher.compare_branches(base_sim_id)
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.scenario_branching")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Branch:
    """A single branch (fork) of a base simulation."""

    branch_id: str
    label_he: str  # e.g. "ליברמן מצביע נגד"
    scenario_diff: dict  # What changed vs base
    simulation_result: Optional[dict] = None
    status: str = "pending"  # pending | running | completed | failed
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "branch_id": self.branch_id,
            "label_he": self.label_he,
            "scenario_diff": self.scenario_diff,
            "status": self.status,
            "error": self.error,
            "simulation_result": self.simulation_result,
        }


# ---------------------------------------------------------------------------
# Brancher
# ---------------------------------------------------------------------------

class ScenarioBrancher:
    """Fork simulations for comparison.

    Maintains a registry of branches per base simulation.  Each branch
    applies a *scenario_diff* to the base simulation's initial conditions
    and runs its own KnessetLoop independently.

    Parameters
    ----------
    orchestrator : KnessetOrchestrator
        The orchestrator instance used to run branched simulations.
    """

    def __init__(self, orchestrator) -> None:
        self._orchestrator = orchestrator
        # base_simulation_id -> list of branches
        self.branches: Dict[str, List[Branch]] = {}

    # ------------------------------------------------------------------
    # Branch creation
    # ------------------------------------------------------------------

    async def create_branch(
        self,
        base_simulation_id: str,
        label_he: str,
        scenario_diff: dict,
    ) -> Branch:
        """Clone a base simulation's initial state and apply a diff.

        Parameters
        ----------
        base_simulation_id : str
            ID of the simulation to fork from.
        label_he : str
            Human-readable Hebrew label (e.g., "ליברמן מצביע נגד").
        scenario_diff : dict
            Modifications to apply.  Supported keys:
            - ``flip_votes``: list of ``{mk_id, new_vote}``
            - ``add_faction_to_coalition``: str (faction name)
            - ``remove_faction_from_coalition``: str (faction name)
            - ``scenario``: full scenario dict for KnessetScenarioEngine

        Returns
        -------
        Branch
            The created branch (status="pending", not yet run).
        """
        branch = Branch(
            branch_id=str(uuid.uuid4())[:10],
            label_he=label_he,
            scenario_diff=scenario_diff,
        )

        if base_simulation_id not in self.branches:
            self.branches[base_simulation_id] = []
        self.branches[base_simulation_id].append(branch)

        logger.info(
            "Created branch '%s' for base %s: %s",
            label_he, base_simulation_id, scenario_diff,
        )
        return branch

    # ------------------------------------------------------------------
    # Run branches
    # ------------------------------------------------------------------

    async def run_branches(
        self,
        base_simulation_id: str,
        question_he: str,
        rounds: int = 5,
    ) -> List[Branch]:
        """Run all pending branches for a base simulation.

        Each branch gets its own simulation via the orchestrator.
        Branches run sequentially to avoid concurrent API cost; callers
        can parallelise externally if desired.

        Parameters
        ----------
        base_simulation_id : str
            The base simulation to fork from.
        question_he : str
            The bill / question (same as base).
        rounds : int
            Number of simulation rounds per branch.

        Returns
        -------
        list[Branch]
            All branches (including previously completed ones).
        """
        branch_list = self.branches.get(base_simulation_id, [])
        if not branch_list:
            logger.warning("No branches found for simulation %s", base_simulation_id)
            return []

        for branch in branch_list:
            if branch.status != "pending":
                continue

            branch.status = "running"
            logger.info("Running branch '%s' (%s)", branch.label_he, branch.branch_id)

            try:
                # Build a scenario dict from the diff
                scenario = self._diff_to_scenario(branch.scenario_diff)
                result = await self._orchestrator.run_simulation(
                    question_he=question_he,
                    rounds=rounds,
                    scenario=scenario,
                )
                branch.simulation_result = result
                branch.status = "completed"
                logger.info("Branch '%s' completed", branch.label_he)

            except Exception as exc:
                branch.status = "failed"
                branch.error = str(exc)
                logger.error(
                    "Branch '%s' failed: %s", branch.label_he, exc, exc_info=True,
                )

        return branch_list

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_branches(self, base_simulation_id: str) -> dict:
        """Compare all branch outcomes against the base simulation.

        Returns
        -------
        dict
            {
                base_result: dict | None,
                branches: [{label_he, branch_id, status, result_summary, diff}],
                analysis_he: str,
            }
        """
        base_result = self._orchestrator.get_simulation_status(base_simulation_id)
        branch_list = self.branches.get(base_simulation_id, [])

        base_outcomes = base_result.get("bill_outcomes", {})
        base_summary = base_result.get("summary", {})

        comparisons: List[dict] = []
        for branch in branch_list:
            entry: Dict[str, Any] = {
                "label_he": branch.label_he,
                "branch_id": branch.branch_id,
                "status": branch.status,
            }

            if branch.status == "completed" and branch.simulation_result:
                branch_outcomes = branch.simulation_result.get("bill_outcomes", {})
                branch_summary = branch.simulation_result.get("summary", {})

                vote_diff = self._compute_vote_diff(base_outcomes, branch_outcomes)
                outcome_diff = self._compute_outcome_diff(base_outcomes, branch_outcomes)
                key_changes = self._find_key_changes(base_summary, branch_summary)

                entry["result_summary"] = {
                    "total_votes_for": branch_summary.get("total_votes_for", 0),
                    "total_votes_against": branch_summary.get("total_votes_against", 0),
                    "user_bill_status": branch_summary.get("user_bill_status", ""),
                }
                entry["vote_diff"] = vote_diff
                entry["outcome_diff"] = outcome_diff
                entry["key_changes"] = key_changes

            elif branch.status == "failed":
                entry["error"] = branch.error

            comparisons.append(entry)

        # Generate Hebrew analysis text
        analysis_he = self._generate_comparison_analysis_he(
            base_summary, comparisons,
        )

        return {
            "base_simulation_id": base_simulation_id,
            "base_result": {
                "total_votes_for": base_summary.get("total_votes_for", 0),
                "total_votes_against": base_summary.get("total_votes_against", 0),
                "user_bill_status": base_summary.get("user_bill_status", ""),
            },
            "branches": comparisons,
            "analysis_he": analysis_he,
        }

    # ------------------------------------------------------------------
    # Auto-branching helpers
    # ------------------------------------------------------------------

    def auto_branch_swing_mks(self, base_result: dict) -> List[dict]:
        """Auto-generate branch diffs by flipping each swing MK.

        Parameters
        ----------
        base_result : dict
            The completed base simulation result (from orchestrator).

        Returns
        -------
        list[dict]
            List of scenario_diffs, each flipping one swing MK's vote.
            Format: ``{flip_votes: [{mk_id, mk_name, original_vote, new_vote}]}``
        """
        summary = base_result.get("summary", {})
        swing_mks = summary.get("swing_mks", [])

        diffs: List[dict] = []
        for mk_info in swing_mks:
            mk_name = mk_info.get("mk_name", "")
            faction = mk_info.get("faction", "")
            current_vote = mk_info.get("vote", "")

            # Flip vote direction
            if current_vote == "\u05d1\u05e2\u05d3":  # בעד
                new_vote = "\u05e0\u05d2\u05d3"  # נגד
            elif current_vote == "\u05e0\u05d2\u05d3":  # נגד
                new_vote = "\u05d1\u05e2\u05d3"  # בעד
            else:
                new_vote = "\u05e0\u05d2\u05d3"  # נמנע -> נגד

            diffs.append({
                "flip_votes": [{
                    "mk_id": mk_info.get("mk_name", ""),  # use name as fallback ID
                    "mk_name": mk_name,
                    "original_vote": current_vote,
                    "new_vote": new_vote,
                }],
                "_label_he": f"{mk_name} ({faction}) מצביע {new_vote} במקום {current_vote}",
            })

        logger.info("Auto-generated %d swing-MK branch diffs", len(diffs))
        return diffs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_to_scenario(scenario_diff: dict) -> Optional[dict]:
        """Convert a branch scenario_diff to a scenario dict for the orchestrator.

        Supports:
        - ``scenario``: pass-through full scenario
        - ``remove_faction_from_coalition``: coalition collapse
        - ``add_faction_to_coalition``: election change (add to coalition)
        - ``flip_votes``: MK defection (simplified)
        """
        # Full scenario passthrough
        if "scenario" in scenario_diff:
            return scenario_diff["scenario"]

        # Faction removal from coalition
        if "remove_faction_from_coalition" in scenario_diff:
            return {
                "type": "coalition_collapse",
                "params": {
                    "leaving_faction": scenario_diff["remove_faction_from_coalition"],
                },
            }

        # Faction addition to coalition
        if "add_faction_to_coalition" in scenario_diff:
            return {
                "type": "election_change",
                "params": {
                    "new_coalition": [],  # will be resolved by scenario engine
                    "winning_party": scenario_diff["add_faction_to_coalition"],
                },
            }

        # Vote flipping -> MK defection (approximation)
        flip_votes = scenario_diff.get("flip_votes", [])
        if flip_votes:
            # Use the first flip as a defection scenario
            first = flip_votes[0]
            return {
                "type": "mk_defection",
                "params": {
                    "mk_id": first.get("mk_id", ""),
                    "from_faction": "",
                    "to_faction": "",  # stays in same faction but votes differently
                },
            }

        # Crisis event
        if "crisis" in scenario_diff:
            return {
                "type": "crisis_event",
                "params": scenario_diff["crisis"],
            }

        return None

    @staticmethod
    def _compute_vote_diff(
        base_outcomes: dict, branch_outcomes: dict,
    ) -> Dict[str, dict]:
        """Compute per-bill vote differences between base and branch."""
        diff: Dict[str, dict] = {}
        all_bills = set(base_outcomes.keys()) | set(branch_outcomes.keys())

        for bill_id in all_bills:
            base_votes = base_outcomes.get(bill_id, {}).get("votes", {})
            branch_votes = branch_outcomes.get(bill_id, {}).get("votes", {})

            bill_diff = {}
            for key in ("\u05d1\u05e2\u05d3", "\u05e0\u05d2\u05d3", "\u05e0\u05de\u05e0\u05e2"):
                base_val = base_votes.get(key, 0)
                branch_val = branch_votes.get(key, 0)
                if base_val != branch_val:
                    bill_diff[key] = {"base": base_val, "branch": branch_val}

            if bill_diff:
                diff[bill_id] = bill_diff

        return diff

    @staticmethod
    def _compute_outcome_diff(
        base_outcomes: dict, branch_outcomes: dict,
    ) -> List[dict]:
        """Find bills whose status changed between base and branch."""
        diffs: List[dict] = []
        for bill_id in base_outcomes:
            base_status = base_outcomes[bill_id].get("status", "")
            branch_status = branch_outcomes.get(bill_id, {}).get("status", "")
            if base_status != branch_status and branch_status:
                diffs.append({
                    "bill_id": bill_id,
                    "base_status": base_status,
                    "branch_status": branch_status,
                    "title_he": base_outcomes[bill_id].get("title_he", ""),
                })
        return diffs

    @staticmethod
    def _find_key_changes(
        base_summary: dict, branch_summary: dict,
    ) -> List[str]:
        """Identify high-level changes between base and branch summaries."""
        changes: List[str] = []

        base_for = base_summary.get("total_votes_for", 0)
        branch_for = branch_summary.get("total_votes_for", 0)
        if base_for != branch_for:
            delta = branch_for - base_for
            sign = "+" if delta > 0 else ""
            changes.append(f"קולות בעד: {base_for} -> {branch_for} ({sign}{delta})")

        base_against = base_summary.get("total_votes_against", 0)
        branch_against = branch_summary.get("total_votes_against", 0)
        if base_against != branch_against:
            delta = branch_against - base_against
            sign = "+" if delta > 0 else ""
            changes.append(f"קולות נגד: {base_against} -> {branch_against} ({sign}{delta})")

        base_status = base_summary.get("user_bill_status", "")
        branch_status = branch_summary.get("user_bill_status", "")
        if base_status != branch_status:
            changes.append(f"סטטוס: {base_status} -> {branch_status}")

        base_swings = len(base_summary.get("swing_mks", []))
        branch_swings = len(branch_summary.get("swing_mks", []))
        if base_swings != branch_swings:
            changes.append(f"ח\"כים נדנדה: {base_swings} -> {branch_swings}")

        return changes

    @staticmethod
    def _generate_comparison_analysis_he(
        base_summary: dict,
        comparisons: List[dict],
    ) -> str:
        """Generate a Hebrew comparison analysis text."""
        lines = ["--- ניתוח השוואתי ---"]

        base_status = base_summary.get("user_bill_status", "לא ידוע")
        base_for = base_summary.get("total_votes_for", 0)
        base_against = base_summary.get("total_votes_against", 0)
        lines.append(f"תוצאת בסיס: {base_status} ({base_for} בעד, {base_against} נגד)")
        lines.append("")

        completed = [c for c in comparisons if c.get("status") == "completed"]
        if not completed:
            lines.append("אין ענפים שהושלמו להשוואה.")
            return "\n".join(lines)

        for comp in completed:
            label = comp.get("label_he", "?")
            result = comp.get("result_summary", {})
            b_for = result.get("total_votes_for", 0)
            b_against = result.get("total_votes_against", 0)
            b_status = result.get("user_bill_status", "?")

            lines.append(f"ענף: {label}")
            lines.append(f"  תוצאה: {b_status} ({b_for} בעד, {b_against} נגד)")

            key_changes = comp.get("key_changes", [])
            if key_changes:
                lines.append("  שינויים עיקריים:")
                for change in key_changes:
                    lines.append(f"    - {change}")

            outcome_diff = comp.get("outcome_diff", [])
            if outcome_diff:
                for od in outcome_diff:
                    lines.append(
                        f"  הצעת חוק '{od.get('title_he', '')}': "
                        f"{od.get('base_status', '')} -> {od.get('branch_status', '')}"
                    )
            lines.append("")

        # Tipping point analysis
        flipped = [
            c for c in completed
            if c.get("result_summary", {}).get("user_bill_status") != base_status
        ]
        if flipped:
            lines.append(f"נקודת מפנה: {len(flipped)} ענפים שינו את תוצאת ההצבעה:")
            for f in flipped:
                lines.append(f"  - {f.get('label_he', '?')}")
        else:
            lines.append("לא נמצאה נקודת מפנה — התוצאה יציבה בכל התרחישים.")

        return "\n".join(lines)
