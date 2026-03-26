"""KnessetSim types — dataclasses for Knesset simulation engine.

Extends the AgentPersona / AgentAction pattern from FastAgentLoop
with Knesset-specific fields: factions, bills, votes, speeches.
All Hebrew text fields use the _he suffix convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNESSET_ACTIONS: List[str] = [
    "PROPOSE_BILL",
    "VOTE",
    "SPEAK_IN_PLENUM",
    "LOBBY",
    "FORM_ALLIANCE",
    "DEFECT",
    "AMEND_BILL",
    "DO_NOTHING",
]

AUXILIARY_ROLES: List[str] = [
    "advisor",      # יועץ פוליטי
    "journalist",   # עיתונאי
    "lobbyist",     # לוביסט
    "legal_advisor", # יועץ משפטי
    "economist",    # כלכלן
]

AUXILIARY_ACTIONS: List[str] = [
    "SPEAK_IN_PLENUM",
    "LOBBY",
    "DO_NOTHING",
]

TYCOON_ACTIONS: List[str] = [
    "ECONOMIC_PRESSURE",
    "THREATEN_RELOCATION",
    "LOBBY",
    "PUBLIC_STATEMENT",
    "DO_NOTHING",
]

ACTIVIST_ACTIONS: List[str] = [
    "PROTEST",
    "PETITION",
    "PUBLIC_PRESSURE",
    "SPEAK_IN_PLENUM",
    "DO_NOTHING",
]

BILL_STATUSES: List[str] = [
    "proposed",
    "committee",
    "first_reading",
    "second_reading",
    "third_reading",
    "passed",
    "failed",
    "withdrawn",
]

RhetoricStyle = Literal["populist", "technocrat", "ideologue"]

VoteValue = Literal["\u05d1\u05e2\u05d3", "\u05e0\u05d2\u05d3", "\u05e0\u05de\u05e0\u05e2"]
# Hebrew: "בעד", "נגד", "נמנע"


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@dataclass
class KnessetPersona:
    """A Knesset member agent persona.

    Extends the AgentPersona pattern with Israeli-politics-specific fields:
    faction affiliation, coalition membership, ideology tags, committee roles,
    and rhetoric style used for LLM prompt generation.
    """

    agent_id: str
    name_he: str
    name_en: str
    faction: str
    faction_id: str
    knesset_person_id: int = 0
    gender: str = "male"
    is_current_mk: bool = True
    coalition_member: bool = False
    influence_score: int = 50
    loyalty_score: float = 0.8
    ideology_tags: List[str] = field(default_factory=list)
    stances: Dict[str, str] = field(default_factory=dict)
    personality: str = ""
    rhetoric_style: str = "technocrat"
    committee_roles: List[str] = field(default_factory=list)
    voting_history_summary: str = ""
    twitter_handle: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict for JSON / DB storage."""
        return {
            "agent_id": self.agent_id,
            "name_he": self.name_he,
            "name_en": self.name_en,
            "faction": self.faction,
            "faction_id": self.faction_id,
            "knesset_person_id": self.knesset_person_id,
            "gender": self.gender,
            "is_current_mk": self.is_current_mk,
            "coalition_member": self.coalition_member,
            "influence_score": self.influence_score,
            "loyalty_score": self.loyalty_score,
            "ideology_tags": self.ideology_tags,
            "stances": self.stances,
            "personality": self.personality,
            "rhetoric_style": self.rhetoric_style,
            "committee_roles": self.committee_roles,
            "voting_history_summary": self.voting_history_summary,
            "twitter_handle": self.twitter_handle,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnessetPersona:
        """Reconstruct from a plain dict."""
        return cls(
            agent_id=data["agent_id"],
            name_he=data["name_he"],
            name_en=data["name_en"],
            faction=data["faction"],
            faction_id=data["faction_id"],
            knesset_person_id=data.get("knesset_person_id", 0),
            gender=data.get("gender", "male"),
            is_current_mk=data.get("is_current_mk", True),
            coalition_member=data.get("coalition_member", False),
            influence_score=data.get("influence_score", 50),
            loyalty_score=data.get("loyalty_score", 0.8),
            ideology_tags=data.get("ideology_tags", []),
            stances=data.get("stances", {}),
            personality=data.get("personality", ""),
            rhetoric_style=data.get("rhetoric_style", "technocrat"),
            committee_roles=data.get("committee_roles", []),
            voting_history_summary=data.get("voting_history_summary", ""),
            twitter_handle=data.get("twitter_handle"),
        )


@dataclass
class AuxiliaryPersona:
    """A non-MK participant in the simulation.

    Advisors, journalists, lobbyists who observe and influence
    but don't vote on legislation.
    """

    agent_id: str
    name_he: str
    name_en: str
    role: str  # one of AUXILIARY_ROLES
    affiliation: str = ""  # party/org they're affiliated with
    influence_score: int = 30
    personality: str = ""
    expertise_areas: List[str] = field(default_factory=list)
    stances: Dict[str, str] = field(default_factory=dict)

    # Role-specific capabilities
    can_vote: bool = False
    can_propose_bill: bool = False
    can_lobby: bool = True
    can_speak: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name_he": self.name_he,
            "name_en": self.name_en,
            "role": self.role,
            "affiliation": self.affiliation,
            "influence_score": self.influence_score,
            "personality": self.personality,
            "expertise_areas": self.expertise_areas,
            "stances": self.stances,
            "can_vote": self.can_vote,
            "can_propose_bill": self.can_propose_bill,
            "can_lobby": self.can_lobby,
            "can_speak": self.can_speak,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuxiliaryPersona":
        return cls(
            agent_id=data["agent_id"],
            name_he=data["name_he"],
            name_en=data.get("name_en", ""),
            role=data["role"],
            affiliation=data.get("affiliation", ""),
            influence_score=data.get("influence_score", 30),
            personality=data.get("personality", ""),
            expertise_areas=data.get("expertise_areas", []),
            stances=data.get("stances", {}),
            can_vote=data.get("can_vote", False),
            can_propose_bill=data.get("can_propose_bill", False),
            can_lobby=data.get("can_lobby", True),
            can_speak=data.get("can_speak", True),
        )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@dataclass
class KnessetAction:
    """A single action taken by a Knesset member in one simulation round.

    Extends the AgentAction pattern with Knesset-specific optional fields:
    bill references, Hebrew vote values, speech text, lobby targets, and
    coalition alliance targets.
    """

    round_num: int
    timestamp: str
    agent_id: str
    agent_name: str
    action_type: str
    bill_id: Optional[str] = None
    vote_value: Optional[str] = None  # "בעד" | "נגד" | "נמנע"
    speech_text: Optional[str] = None
    reasoning: str = ""
    target_mk_id: Optional[str] = None
    coalition_target: Optional[str] = None
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict for JSON / report output."""
        return {
            "round_num": self.round_num,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_type": self.action_type,
            "bill_id": self.bill_id,
            "vote_value": self.vote_value,
            "speech_text": self.speech_text,
            "reasoning": self.reasoning,
            "target_mk_id": self.target_mk_id,
            "coalition_target": self.coalition_target,
            "success": self.success,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnessetAction:
        """Reconstruct from a plain dict."""
        return cls(
            round_num=data["round_num"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            agent_id=data["agent_id"],
            agent_name=data["agent_name"],
            action_type=data["action_type"],
            bill_id=data.get("bill_id"),
            vote_value=data.get("vote_value"),
            speech_text=data.get("speech_text"),
            reasoning=data.get("reasoning", ""),
            target_mk_id=data.get("target_mk_id"),
            coalition_target=data.get("coalition_target"),
            success=data.get("success", True),
        )


# ---------------------------------------------------------------------------
# Vote / Amendment / Speech records
# ---------------------------------------------------------------------------

@dataclass
class VoteRecord:
    """A single MK's vote on a bill."""

    mk_id: str
    mk_name: str
    vote: str  # "בעד" | "נגד" | "נמנע"
    round_num: int = 0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mk_id": self.mk_id,
            "mk_name": self.mk_name,
            "vote": self.vote,
            "round_num": self.round_num,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VoteRecord:
        return cls(
            mk_id=data["mk_id"],
            mk_name=data["mk_name"],
            vote=data["vote"],
            round_num=data.get("round_num", 0),
            reasoning=data.get("reasoning", ""),
        )


@dataclass
class Amendment:
    """A proposed amendment to a bill."""

    mk_id: str
    text_he: str
    round_num: int = 0
    accepted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mk_id": self.mk_id,
            "text_he": self.text_he,
            "round_num": self.round_num,
            "accepted": self.accepted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Amendment:
        return cls(
            mk_id=data["mk_id"],
            text_he=data["text_he"],
            round_num=data.get("round_num", 0),
            accepted=data.get("accepted", False),
        )


@dataclass
class Speech:
    """A plenum speech by an MK."""

    mk_id: str
    mk_name: str
    topic: str
    content_he: str
    round_num: int = 0
    stance: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mk_id": self.mk_id,
            "mk_name": self.mk_name,
            "topic": self.topic,
            "content_he": self.content_he,
            "round_num": self.round_num,
            "stance": self.stance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Speech:
        return cls(
            mk_id=data["mk_id"],
            mk_name=data["mk_name"],
            topic=data["topic"],
            content_he=data["content_he"],
            round_num=data.get("round_num", 0),
            stance=data.get("stance", ""),
        )


# ---------------------------------------------------------------------------
# Bill state
# ---------------------------------------------------------------------------

@dataclass
class BillState:
    """Full state of a legislative bill through the Knesset lifecycle.

    Tracks sponsor, status progression, vote tallies, individual vote records,
    amendments, and timestamps.
    """

    bill_id: str
    title_he: str
    summary_he: str
    category: str
    sponsor_id: str
    sponsor_name: str
    status: str = "proposed"  # one of BILL_STATUSES
    votes: Dict[str, int] = field(default_factory=lambda: {
        "for": 0,
        "against": 0,
        "abstain": 0,
        "absent": 0,
    })
    vote_records: Dict[str, VoteRecord] = field(default_factory=dict)
    amendments: List[Amendment] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict, recursing into nested records."""
        return {
            "bill_id": self.bill_id,
            "title_he": self.title_he,
            "summary_he": self.summary_he,
            "category": self.category,
            "sponsor_id": self.sponsor_id,
            "sponsor_name": self.sponsor_name,
            "status": self.status,
            "votes": self.votes,
            "vote_records": {
                mk_id: vr.to_dict() for mk_id, vr in self.vote_records.items()
            },
            "amendments": [a.to_dict() for a in self.amendments],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BillState:
        """Reconstruct from a plain dict, including nested records."""
        vote_records = {
            mk_id: VoteRecord.from_dict(vr)
            for mk_id, vr in data.get("vote_records", {}).items()
        }
        amendments = [
            Amendment.from_dict(a) for a in data.get("amendments", [])
        ]
        return cls(
            bill_id=data["bill_id"],
            title_he=data["title_he"],
            summary_he=data.get("summary_he", ""),
            category=data.get("category", ""),
            sponsor_id=data["sponsor_id"],
            sponsor_name=data["sponsor_name"],
            status=data.get("status", "proposed"),
            votes=data.get("votes", {"for": 0, "against": 0, "abstain": 0, "absent": 0}),
            vote_records=vote_records,
            amendments=amendments,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )

    def advance_status(self) -> bool:
        """Move bill to the next status in the lifecycle. Returns False if already terminal."""
        try:
            idx = BILL_STATUSES.index(self.status)
        except ValueError:
            return False
        # "passed", "failed", "withdrawn" are terminal
        if self.status in ("passed", "failed", "withdrawn"):
            return False
        if idx + 1 < len(BILL_STATUSES):
            self.status = BILL_STATUSES[idx + 1]
            self.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def record_vote(self, vote_record: VoteRecord) -> None:
        """Register a single MK's vote and update tallies."""
        self.vote_records[vote_record.mk_id] = vote_record
        # Update tallies
        vote_map = {
            "\u05d1\u05e2\u05d3": "for",      # בעד
            "\u05e0\u05d2\u05d3": "against",   # נגד
            "\u05e0\u05de\u05e0\u05e2": "abstain",  # נמנע
        }
        tally_key = vote_map.get(vote_record.vote)
        if tally_key:
            # Recount from scratch to stay consistent
            self.votes = {"for": 0, "against": 0, "abstain": 0, "absent": 0}
            for vr in self.vote_records.values():
                k = vote_map.get(vr.vote, "absent")
                self.votes[k] += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()
