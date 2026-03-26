"""Extended Knesset data types for real-world parliament data.

Extends the simulation types from types.py with data-rich models
for budgets, protocols, committees, and more — all populated from
real Knesset data sources (OData, obudget.org, protocols, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .types import KnessetPersona, BillState


# ---------------------------------------------------------------------------
# KnessetMember — rich real-data MK profile
# ---------------------------------------------------------------------------

@dataclass
class KnessetMember(KnessetPersona):
    """Full MK profile enriched with real data for driving simulations.

    Extends KnessetPersona with real voting records, speech topics,
    budget interests, committee history, and lobby connections.
    """

    knesset_numbers: List[int] = field(default_factory=list)
    birth_date: Optional[str] = None
    party_history: List[Dict[str, Any]] = field(default_factory=list)
    committee_memberships: List[Dict[str, Any]] = field(default_factory=list)
    bills_proposed: List[str] = field(default_factory=list)
    voting_record: Dict[str, Dict[str, int]] = field(default_factory=dict)
    speech_topics: Dict[str, int] = field(default_factory=dict)
    budget_interests: List[Dict[str, Any]] = field(default_factory=list)
    lobby_connections: List[Dict[str, Any]] = field(default_factory=list)
    social_media: Dict[str, str] = field(default_factory=dict)
    education: str = ""
    profession: str = ""
    residence: str = ""
    email: str = ""
    sources: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "knesset_numbers": self.knesset_numbers,
            "birth_date": self.birth_date,
            "party_history": self.party_history,
            "committee_memberships": self.committee_memberships,
            "bills_proposed": self.bills_proposed,
            "voting_record": self.voting_record,
            "speech_topics": self.speech_topics,
            "budget_interests": self.budget_interests,
            "lobby_connections": self.lobby_connections,
            "social_media": self.social_media,
            "education": self.education,
            "profession": self.profession,
            "residence": self.residence,
            "email": self.email,
            "sources": self.sources,
        })
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnessetMember:
        return cls(
            agent_id=data.get("agent_id", ""),
            name_he=data.get("name_he", ""),
            name_en=data.get("name_en", ""),
            faction=data.get("faction", ""),
            faction_id=data.get("faction_id", ""),
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
            knesset_numbers=data.get("knesset_numbers", []),
            birth_date=data.get("birth_date"),
            party_history=data.get("party_history", []),
            committee_memberships=data.get("committee_memberships", []),
            bills_proposed=data.get("bills_proposed", []),
            voting_record=data.get("voting_record", {}),
            speech_topics=data.get("speech_topics", {}),
            budget_interests=data.get("budget_interests", []),
            lobby_connections=data.get("lobby_connections", []),
            social_media=data.get("social_media", {}),
            education=data.get("education", ""),
            profession=data.get("profession", ""),
            residence=data.get("residence", ""),
            email=data.get("email", ""),
            sources=data.get("sources", []),
        )


# ---------------------------------------------------------------------------
# Bill — extends BillState with real legislative data
# ---------------------------------------------------------------------------

@dataclass
class Bill(BillState):
    """Full bill with real legislative history from Knesset data."""

    knesset_bill_id: int = 0
    knesset_num: int = 25
    bill_type: str = ""  # government, private, committee
    initiators: List[str] = field(default_factory=list)
    committee_id: Optional[str] = None
    committee_discussions: List[Dict[str, Any]] = field(default_factory=list)
    full_text_url: str = ""
    related_budget_codes: List[str] = field(default_factory=list)
    amendment_to: Optional[str] = None
    passage_date: Optional[str] = None
    law_number: Optional[str] = None
    public_mentions: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "knesset_bill_id": self.knesset_bill_id,
            "knesset_num": self.knesset_num,
            "bill_type": self.bill_type,
            "initiators": self.initiators,
            "committee_id": self.committee_id,
            "committee_discussions": self.committee_discussions,
            "full_text_url": self.full_text_url,
            "related_budget_codes": self.related_budget_codes,
            "amendment_to": self.amendment_to,
            "passage_date": self.passage_date,
            "law_number": self.law_number,
            "public_mentions": self.public_mentions,
        })
        return d


# ---------------------------------------------------------------------------
# BudgetItem — government budget line from obudget.org
# ---------------------------------------------------------------------------

@dataclass
class BudgetItem:
    """Government budget line item from obudget.org."""

    budget_code: str
    title_he: str
    ministry: str
    program: str
    sub_program: str = ""
    year: int = 0
    net_allocated: float = 0.0
    net_revised: float = 0.0
    net_used: float = 0.0
    change_pct: float = 0.0
    history: List[Dict[str, float]] = field(default_factory=list)
    related_entities: List[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_code": self.budget_code,
            "title_he": self.title_he,
            "ministry": self.ministry,
            "program": self.program,
            "sub_program": self.sub_program,
            "year": self.year,
            "net_allocated": self.net_allocated,
            "net_revised": self.net_revised,
            "net_used": self.net_used,
            "change_pct": self.change_pct,
            "history": self.history,
            "related_entities": self.related_entities,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BudgetItem:
        return cls(**{k: data.get(k, v) for k, v in {
            "budget_code": "", "title_he": "", "ministry": "",
            "program": "", "sub_program": "", "year": 0,
            "net_allocated": 0.0, "net_revised": 0.0, "net_used": 0.0,
            "change_pct": 0.0, "history": [], "related_entities": [],
            "source_url": "",
        }.items()})


# ---------------------------------------------------------------------------
# BudgetSupport — government grant/support to a recipient
# ---------------------------------------------------------------------------

@dataclass
class BudgetSupport:
    """Government support/grant to a specific recipient."""

    support_id: str
    recipient_name: str
    recipient_entity_id: Optional[str] = None
    ministry: str = ""
    budget_code: str = ""
    purpose: str = ""
    amount_approved: float = 0.0
    amount_paid: float = 0.0
    year: int = 0
    source_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "support_id": self.support_id,
            "recipient_name": self.recipient_name,
            "recipient_entity_id": self.recipient_entity_id,
            "ministry": self.ministry,
            "budget_code": self.budget_code,
            "purpose": self.purpose,
            "amount_approved": self.amount_approved,
            "amount_paid": self.amount_paid,
            "year": self.year,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BudgetSupport:
        return cls(**{k: data.get(k, v) for k, v in {
            "support_id": "", "recipient_name": "",
            "recipient_entity_id": None, "ministry": "",
            "budget_code": "", "purpose": "",
            "amount_approved": 0.0, "amount_paid": 0.0,
            "year": 0, "source_url": "",
        }.items()})


# ---------------------------------------------------------------------------
# Committee
# ---------------------------------------------------------------------------

@dataclass
class Committee:
    """Knesset committee with members and meeting history."""

    committee_id: str
    name_he: str
    name_en: str = ""
    committee_type: str = ""  # standing, special, inquiry, subcommittee
    knesset_num: int = 25
    chair_mk_id: Optional[str] = None
    members: List[str] = field(default_factory=list)
    recent_topics: List[str] = field(default_factory=list)
    meeting_count: int = 0
    last_meeting_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "committee_id": self.committee_id,
            "name_he": self.name_he,
            "name_en": self.name_en,
            "committee_type": self.committee_type,
            "knesset_num": self.knesset_num,
            "chair_mk_id": self.chair_mk_id,
            "members": self.members,
            "recent_topics": self.recent_topics,
            "meeting_count": self.meeting_count,
            "last_meeting_date": self.last_meeting_date,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Committee:
        return cls(**{k: data.get(k, v) for k, v in {
            "committee_id": "", "name_he": "", "name_en": "",
            "committee_type": "", "knesset_num": 25,
            "chair_mk_id": None, "members": [],
            "recent_topics": [], "meeting_count": 0,
            "last_meeting_date": None,
        }.items()})


# ---------------------------------------------------------------------------
# ProtocolRecord — single speech from a Knesset protocol
# ---------------------------------------------------------------------------

@dataclass
class ProtocolRecord:
    """A single speech/statement from a Knesset protocol."""

    protocol_id: str
    session_type: str  # plenum, committee
    session_id: str
    speaker_mk_id: Optional[str] = None
    speaker_name: str = ""
    speaker_role: str = ""  # MK, minister, witness, chair
    content_he: str = ""
    date: str = ""
    topic: str = ""
    referenced_bills: List[str] = field(default_factory=list)
    referenced_budgets: List[str] = field(default_factory=list)
    sentiment: Optional[str] = None
    stance_on_topic: Optional[str] = None
    mentioned_entities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_id": self.protocol_id,
            "session_type": self.session_type,
            "session_id": self.session_id,
            "speaker_mk_id": self.speaker_mk_id,
            "speaker_name": self.speaker_name,
            "speaker_role": self.speaker_role,
            "content_he": self.content_he,
            "date": self.date,
            "topic": self.topic,
            "referenced_bills": self.referenced_bills,
            "referenced_budgets": self.referenced_budgets,
            "sentiment": self.sentiment,
            "stance_on_topic": self.stance_on_topic,
            "mentioned_entities": self.mentioned_entities,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProtocolRecord:
        return cls(**{k: data.get(k, v) for k, v in {
            "protocol_id": "", "session_type": "",
            "session_id": "", "speaker_mk_id": None,
            "speaker_name": "", "speaker_role": "",
            "content_he": "", "date": "", "topic": "",
            "referenced_bills": [], "referenced_budgets": [],
            "sentiment": None, "stance_on_topic": None,
            "mentioned_entities": [],
        }.items()})


# ---------------------------------------------------------------------------
# Faction
# ---------------------------------------------------------------------------

@dataclass
class Faction:
    """Political faction/party in the Knesset."""

    faction_id: str
    name_he: str
    name_en: str = ""
    knesset_num: int = 25
    seats: int = 0
    is_coalition: bool = False
    coalition_agreement_url: str = ""
    ideology_tags: List[str] = field(default_factory=list)
    leader_mk_id: Optional[str] = None
    members: List[str] = field(default_factory=list)
    voting_discipline: float = 0.0
    key_budget_interests: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "faction_id": self.faction_id,
            "name_he": self.name_he,
            "name_en": self.name_en,
            "knesset_num": self.knesset_num,
            "seats": self.seats,
            "is_coalition": self.is_coalition,
            "coalition_agreement_url": self.coalition_agreement_url,
            "ideology_tags": self.ideology_tags,
            "leader_mk_id": self.leader_mk_id,
            "members": self.members,
            "voting_discipline": self.voting_discipline,
            "key_budget_interests": self.key_budget_interests,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Faction:
        return cls(**{k: data.get(k, v) for k, v in {
            "faction_id": "", "name_he": "", "name_en": "",
            "knesset_num": 25, "seats": 0, "is_coalition": False,
            "coalition_agreement_url": "", "ideology_tags": [],
            "leader_mk_id": None, "members": [],
            "voting_discipline": 0.0, "key_budget_interests": [],
        }.items()})


# ---------------------------------------------------------------------------
# InterestLink — MK-to-entity connection
# ---------------------------------------------------------------------------

@dataclass
class InterestLink:
    """Connection between an MK and an external interest."""

    link_id: str
    mk_id: str
    entity_id: str
    link_type: str  # donation, lobbying, family, employment, board_member, ideology
    description_he: str = ""
    amount: Optional[float] = None
    period: str = ""
    source_url: str = ""
    confidence: float = 0.8

    def to_dict(self) -> Dict[str, Any]:
        return {
            "link_id": self.link_id,
            "mk_id": self.mk_id,
            "entity_id": self.entity_id,
            "link_type": self.link_type,
            "description_he": self.description_he,
            "amount": self.amount,
            "period": self.period,
            "source_url": self.source_url,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterestLink:
        return cls(**{k: data.get(k, v) for k, v in {
            "link_id": "", "mk_id": "", "entity_id": "",
            "link_type": "", "description_he": "",
            "amount": None, "period": "",
            "source_url": "", "confidence": 0.8,
        }.items()})


# ---------------------------------------------------------------------------
# CollectionResult — returned by collectors
# ---------------------------------------------------------------------------

@dataclass
class CollectionResult:
    """Result from a single collector run."""

    source_id: str
    items_new: int = 0
    items_updated: int = 0
    items_skipped: int = 0
    new_cursor: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "items_new": self.items_new,
            "items_updated": self.items_updated,
            "items_skipped": self.items_skipped,
            "new_cursor": self.new_cursor,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }
