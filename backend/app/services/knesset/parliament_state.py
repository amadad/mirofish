"""ParliamentState — in-memory Knesset simulation state engine.

Tracks bills, votes, speeches, lobbying, alliances, and defections.
Deterministic bill-advancement logic after each round.
Produces Hebrew-language summaries for agent prompts.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .types import (
    BILL_STATUSES,
    BillState,
    KnessetAction,
    Speech,
    VoteRecord,
)

logger = logging.getLogger("mirofish.knesset.parliament_state")

# Ordered progression for deterministic advancement
_STATUS_ORDER = {s: i for i, s in enumerate(BILL_STATUSES)}

# Thresholds
_ABSOLUTE_MAJORITY = 61  # Knesset has 120 seats; 61 = absolute majority
_SUPPORT_THRESHOLD_FOR_COMMITTEE = 3  # min support signals to move proposed -> committee


class ParliamentState:
    """In-memory Knesset parliament state for KnessetSim."""

    def __init__(self) -> None:
        # --- core state ---
        self.bills: Dict[str, BillState] = {}
        self.coalition_map: Dict[str, str] = {}  # faction_name -> "coalition" | "opposition"
        self.coalition_factions: List[str] = []
        self.opposition_factions: List[str] = []
        self.coalition_seats: int = 0
        self.opposition_seats: int = 0

        # --- records ---
        self.voting_records: List[VoteRecord] = []
        self.speeches: List[Speech] = []
        self.committee_assignments: Dict[str, List[str]] = {}  # committee -> [mk_ids]
        self.lobbying_log: List[dict] = []
        self.alliance_proposals: List[dict] = []
        self.defections: List[dict] = []

        # --- round tracking ---
        self.current_round: int = 0

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def apply_action(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        """Dispatch a KnessetAction to the appropriate handler."""
        atype = action.action_type.upper()
        handler = {
            "PROPOSE_BILL": self._handle_propose_bill,
            "VOTE": self._handle_vote,
            "SPEAK": self._handle_speak,
            "LOBBY": self._handle_lobby,
            "FORM_ALLIANCE": self._handle_form_alliance,
            "DEFECT": self._handle_defect,
            "AMEND_BILL": self._handle_amend_bill,
            "DO_NOTHING": lambda *_args: None,
        }.get(atype)

        if handler is None:
            logger.warning("Unknown action type %s from %s", atype, mk_name)
            return

        handler(mk_id, mk_name, action)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _handle_propose_bill(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        bill_id = action.bill_id or f"bill_{len(self.bills)}"
        if bill_id in self.bills:
            logger.info("Bill %s already exists, skipping proposal by %s", bill_id, mk_name)
            return

        self.bills[bill_id] = BillState(
            bill_id=bill_id,
            title_he=action.speech_text or f"הצעת חוק מאת {mk_name}",
            summary_he=action.reasoning or "",
            category="כללי",
            sponsor_id=mk_id,
            sponsor_name=mk_name,
            status="proposed",
            votes={"בעד": 0, "נגד": 0, "נמנע": 0},
            vote_records={},
        )
        logger.info("Bill %s proposed by %s (%s)", bill_id, mk_name, mk_id)

    def _handle_vote(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        bill_id = action.bill_id
        if not bill_id or bill_id not in self.bills:
            logger.warning("Vote from %s on unknown bill %s", mk_name, bill_id)
            return

        bill = self.bills[bill_id]
        vote_value = action.vote_value or "נמנע"

        # Prevent double-voting in the same round
        existing_key = f"{mk_id}_r{self.current_round}"
        if existing_key in bill.vote_records:
            logger.info("Duplicate vote from %s on %s in round %d", mk_name, bill_id, self.current_round)
            return

        # Record vote
        if vote_value in bill.votes:
            bill.votes[vote_value] += 1
        else:
            bill.votes[vote_value] = 1

        record = VoteRecord(
            mk_id=mk_id,
            mk_name=mk_name,
            vote=vote_value,
            round_num=self.current_round,
            reasoning=action.reasoning or "",
        )
        bill.vote_records[existing_key] = record
        self.voting_records.append(record)
        logger.info("%s voted %s on %s", mk_name, vote_value, bill_id)

    def _handle_speak(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        speech = Speech(
            mk_id=mk_id,
            mk_name=mk_name,
            topic=action.bill_id or "כללי",
            content_he=action.speech_text or "",
            round_num=self.current_round,
            stance=action.reasoning or "ניטרלי",
        )
        self.speeches.append(speech)
        logger.info("Speech by %s on topic %s", mk_name, speech.topic)

    def _handle_lobby(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        entry = {
            "lobbyist_id": mk_id,
            "lobbyist_name": mk_name,
            "target_mk_id": action.target_mk_id or "",
            "bill_id": action.bill_id or "",
            "reasoning": action.reasoning or "",
            "round_num": self.current_round,
        }
        self.lobbying_log.append(entry)
        logger.info("%s lobbied %s regarding %s", mk_name, action.target_mk_id, action.bill_id)

    def _handle_form_alliance(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        proposal = {
            "proposer_id": mk_id,
            "proposer_name": mk_name,
            "target_mk_id": action.target_mk_id or "",
            "bill_id": action.bill_id or "",
            "reasoning": action.reasoning or "",
            "round_num": self.current_round,
        }
        self.alliance_proposals.append(proposal)
        logger.info("%s proposed alliance with %s", mk_name, action.target_mk_id)

    def _handle_defect(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        defection = {
            "mk_id": mk_id,
            "mk_name": mk_name,
            "bill_id": action.bill_id or "",
            "reasoning": action.reasoning or "",
            "round_num": self.current_round,
        }
        self.defections.append(defection)
        logger.info("DEFECTION: %s broke ranks — %s", mk_name, action.reasoning)

    def _handle_amend_bill(self, mk_id: str, mk_name: str, action: KnessetAction) -> None:
        bill_id = action.bill_id
        if not bill_id or bill_id not in self.bills:
            logger.warning("Amend from %s on unknown bill %s", mk_name, bill_id)
            return

        bill = self.bills[bill_id]
        amendment_text = action.speech_text or ""
        if amendment_text:
            bill.summary_he += f"\n[תיקון מאת {mk_name}]: {amendment_text}"
        logger.info("%s amended bill %s", mk_name, bill_id)

    # ------------------------------------------------------------------
    # Bill advancement — deterministic, called after each round
    # ------------------------------------------------------------------

    def advance_bills(self) -> List[str]:
        """Advance bills through legislative stages. Returns list of status-change messages."""
        changes: List[str] = []

        for bill_id, bill in self.bills.items():
            old_status = bill.status
            votes_for = bill.votes.get("בעד", 0)
            votes_against = bill.votes.get("נגד", 0)

            if bill.status == "proposed":
                # Move to committee if enough support signals (votes + lobbying)
                support_signals = votes_for + sum(
                    1 for entry in self.lobbying_log
                    if entry.get("bill_id") == bill_id
                )
                if support_signals >= _SUPPORT_THRESHOLD_FOR_COMMITTEE:
                    bill.status = "committee"

            elif bill.status == "committee":
                # Committee stage: auto-advance to first reading after 1 round in committee
                # (committee deliberation is implicit)
                bill.status = "first_reading"

            elif bill.status == "first_reading":
                if votes_for > votes_against:
                    bill.status = "second_reading"
                elif votes_against > votes_for:
                    bill.status = "failed"

            elif bill.status == "second_reading":
                if votes_for > votes_against:
                    bill.status = "third_reading"
                elif votes_against > votes_for:
                    bill.status = "failed"

            elif bill.status == "third_reading":
                if votes_for >= _ABSOLUTE_MAJORITY:
                    bill.status = "passed"
                elif votes_against > 60:
                    bill.status = "failed"

            if bill.status != old_status:
                msg = f"הצ\"ח {bill.title_he} ({bill_id}): {old_status} -> {bill.status}"
                changes.append(msg)
                logger.info("Bill advanced: %s %s -> %s", bill_id, old_status, bill.status)

        return changes

    # ------------------------------------------------------------------
    # Summaries for agent prompts
    # ------------------------------------------------------------------

    def get_parliament_summary(self, mk_id: Optional[str] = None) -> str:
        """Hebrew summary of parliament state for agent prompts."""
        lines: List[str] = []

        # --- Coalition status ---
        lines.append("=== מצב הכנסת ===")
        lines.append(f"קואליציה: {self.coalition_seats} מושבים | אופוזיציה: {self.opposition_seats} מושבים")
        if self.coalition_factions:
            lines.append(f"סיעות קואליציה: {', '.join(self.coalition_factions)}")
        if self.opposition_factions:
            lines.append(f"סיעות אופוזיציה: {', '.join(self.opposition_factions)}")
        lines.append("")

        # --- Pending bills ---
        active_bills = [b for b in self.bills.values() if b.status not in ("passed", "failed", "withdrawn")]
        if active_bills:
            lines.append("=== הצעות חוק פעילות ===")
            for bill in active_bills:
                v_for = bill.votes.get("בעד", 0)
                v_against = bill.votes.get("נגד", 0)
                v_abstain = bill.votes.get("נמנע", 0)
                lines.append(
                    f"  {bill.title_he} [{bill.bill_id}] — שלב: {bill.status} "
                    f"| בעד: {v_for} נגד: {v_against} נמנע: {v_abstain}"
                )
            lines.append("")

        # --- Passed / failed bills ---
        resolved = [b for b in self.bills.values() if b.status in ("passed", "failed")]
        if resolved:
            lines.append("=== הצעות שהוכרעו ===")
            for bill in resolved:
                status_he = "אושרה" if bill.status == "passed" else "נפלה"
                lines.append(f"  {bill.title_he} — {status_he}")
            lines.append("")

        # --- Recent speeches (last 5) ---
        recent_speeches = self.speeches[-5:]
        if recent_speeches:
            lines.append("=== נאומים אחרונים ===")
            for s in recent_speeches:
                preview = s.content_he[:80] + "..." if len(s.content_he) > 80 else s.content_he
                lines.append(f"  ח\"כ {s.mk_name} ({s.topic}): {preview}")
            lines.append("")

        # --- Lobbying directed at this MK ---
        if mk_id:
            directed = [
                entry for entry in self.lobbying_log
                if entry.get("target_mk_id") == mk_id
            ]
            if directed:
                lines.append("=== לובינג כלפיך ===")
                for entry in directed[-5:]:
                    lines.append(
                        f"  ח\"כ {entry['lobbyist_name']} ביקש ממך לתמוך ב-{entry.get('bill_id', '?')} "
                        f"— {entry.get('reasoning', '')[:60]}"
                    )
                lines.append("")

        # --- Recent defections ---
        if self.defections:
            lines.append("=== מרידות אחרונות ===")
            for d in self.defections[-3:]:
                lines.append(f"  ח\"כ {d['mk_name']} שבר/ה משמעת — {d.get('reasoning', '')[:60]}")
            lines.append("")

        return "\n".join(lines) if lines else "(אין מידע פרלמנטרי)"

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_attendance_stats(self) -> dict:
        """Return per-MK action counts vs DO_NOTHING per round."""
        stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"actions": 0, "idle": 0})
        # We track from voting_records + speeches + lobbying_log
        active_mk_rounds: set = set()

        for vr in self.voting_records:
            key = f"{vr.mk_id}_r{vr.round_num}"
            active_mk_rounds.add(key)
            stats[vr.mk_id]["actions"] += 1

        for sp in self.speeches:
            key = f"{sp.mk_id}_r{sp.round_num}"
            active_mk_rounds.add(key)
            stats[sp.mk_id]["actions"] += 1

        for entry in self.lobbying_log:
            key = f"{entry['lobbyist_id']}_r{entry['round_num']}"
            active_mk_rounds.add(key)
            stats[entry["lobbyist_id"]]["actions"] += 1

        return dict(stats)

    def get_faction_cohesion(self, faction_members: List[str]) -> float:
        """Return 0.0-1.0 cohesion score for a group of MK IDs based on voting alignment.

        Args:
            faction_members: list of mk_id strings belonging to the faction.

        Returns:
            1.0 if all members always vote the same, 0.0 if completely split.
            Returns 1.0 if no votes recorded (no data = no disagreement).
        """
        if not faction_members:
            return 1.0

        member_set = set(faction_members)

        # Group votes by bill
        bill_votes: Dict[str, Dict[str, str]] = defaultdict(dict)  # bill_id -> {mk_id: vote}
        for vr in self.voting_records:
            if vr.mk_id in member_set:
                # Use latest vote per bill per member
                bill_votes[f"bill_{vr.round_num}"][vr.mk_id] = vr.vote

        if not bill_votes:
            return 1.0

        agreements = 0
        total_pairs = 0

        for _bill_id, votes in bill_votes.items():
            voters = list(votes.values())
            n = len(voters)
            if n < 2:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    total_pairs += 1
                    if voters[i] == voters[j]:
                        agreements += 1

        if total_pairs == 0:
            return 1.0

        return agreements / total_pairs

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize full parliament state to dict."""
        return {
            "bills": {
                bid: {
                    "bill_id": b.bill_id,
                    "title_he": b.title_he,
                    "summary_he": b.summary_he,
                    "sponsor_id": b.sponsor_id,
                    "status": b.status,
                    "votes": b.votes,
                    "vote_records": {
                        k: {
                            "mk_id": vr.mk_id,
                            "mk_name": vr.mk_name,
                            "vote": vr.vote,
                            "round_num": vr.round_num,
                            "reasoning": vr.reasoning,
                        }
                        for k, vr in b.vote_records.items()
                    },
                }
                for bid, b in self.bills.items()
            },
            "coalition_map": self.coalition_map,
            "coalition_factions": self.coalition_factions,
            "opposition_factions": self.opposition_factions,
            "coalition_seats": self.coalition_seats,
            "opposition_seats": self.opposition_seats,
            "voting_records": [
                {
                    "mk_id": vr.mk_id,
                    "mk_name": vr.mk_name,
                    "vote": vr.vote,
                    "round_num": vr.round_num,
                    "reasoning": vr.reasoning,
                }
                for vr in self.voting_records
            ],
            "speeches": [
                {
                    "mk_id": s.mk_id,
                    "mk_name": s.mk_name,
                    "topic": s.topic,
                    "content_he": s.content_he,
                    "round_num": s.round_num,
                    "stance": s.stance,
                }
                for s in self.speeches
            ],
            "committee_assignments": self.committee_assignments,
            "lobbying_log": self.lobbying_log,
            "alliance_proposals": self.alliance_proposals,
            "defections": self.defections,
            "current_round": self.current_round,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParliamentState":
        """Deserialize parliament state from dict."""
        state = cls()

        state.coalition_map = data.get("coalition_map", {})
        state.coalition_factions = data.get("coalition_factions", [])
        state.opposition_factions = data.get("opposition_factions", [])
        state.coalition_seats = data.get("coalition_seats", 0)
        state.opposition_seats = data.get("opposition_seats", 0)
        state.committee_assignments = data.get("committee_assignments", {})
        state.lobbying_log = data.get("lobbying_log", [])
        state.alliance_proposals = data.get("alliance_proposals", [])
        state.defections = data.get("defections", [])
        state.current_round = data.get("current_round", 0)

        # Restore bills
        for bid, bdata in data.get("bills", {}).items():
            vote_records = {}
            for k, vrd in bdata.get("vote_records", {}).items():
                vote_records[k] = VoteRecord(
                    mk_id=vrd["mk_id"],
                    mk_name=vrd["mk_name"],
                    vote=vrd["vote"],
                    round_num=vrd["round_num"],
                    reasoning=vrd.get("reasoning", ""),
                )
            state.bills[bid] = BillState(
                bill_id=bdata["bill_id"],
                title_he=bdata["title_he"],
                summary_he=bdata.get("summary_he", ""),
                sponsor_id=bdata["sponsor_id"],
                status=bdata["status"],
                votes=bdata.get("votes", {"בעד": 0, "נגד": 0, "נמנע": 0}),
                vote_records=vote_records,
            )

        # Restore voting records
        for vrd in data.get("voting_records", []):
            state.voting_records.append(VoteRecord(
                mk_id=vrd["mk_id"],
                mk_name=vrd["mk_name"],
                vote=vrd["vote"],
                round_num=vrd["round_num"],
                reasoning=vrd.get("reasoning", ""),
            ))

        # Restore speeches
        for sd in data.get("speeches", []):
            state.speeches.append(Speech(
                mk_id=sd["mk_id"],
                mk_name=sd["mk_name"],
                topic=sd["topic"],
                content_he=sd["content_he"],
                round_num=sd["round_num"],
                stance=sd.get("stance", ""),
            ))

        return state
