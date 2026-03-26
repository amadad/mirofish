"""Knesset domain ontology — entity types, relationship types, and semantic fields.

Defines the knowledge graph schema for the Knesset parliament database.
Used by collectors to classify entities and by the semantic pipeline
to extract typed relationships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Entity type definitions
# ---------------------------------------------------------------------------

ENTITY_TYPES: Dict[str, Dict[str, str]] = {
    "MK": {
        "label_he": "חבר כנסת",
        "label_en": "Member of Knesset",
        "graph_label": "MK",
    },
    "Faction": {
        "label_he": "סיעה",
        "label_en": "Faction",
        "graph_label": "Faction",
    },
    "Bill": {
        "label_he": "הצעת חוק",
        "label_en": "Bill",
        "graph_label": "Bill",
    },
    "Committee": {
        "label_he": "ועדה",
        "label_en": "Committee",
        "graph_label": "Committee",
    },
    "BudgetLine": {
        "label_he": "סעיף תקציבי",
        "label_en": "Budget Line",
        "graph_label": "BudgetLine",
    },
    "BudgetSupport": {
        "label_he": "תמיכה תקציבית",
        "label_en": "Budget Support",
        "graph_label": "BudgetSupport",
    },
    "Organization": {
        "label_he": "ארגון",
        "label_en": "Organization",
        "graph_label": "Organization",
    },
    "Person": {
        "label_he": "אדם",
        "label_en": "Person",
        "graph_label": "Person",
    },
    "Location": {
        "label_he": "מיקום",
        "label_en": "Location",
        "graph_label": "Location",
    },
    "Law": {
        "label_he": "חוק",
        "label_en": "Law",
        "graph_label": "Law",
    },
    "Protocol": {
        "label_he": "פרוטוקול",
        "label_en": "Protocol",
        "graph_label": "Protocol",
    },
    "Topic": {
        "label_he": "נושא",
        "label_en": "Topic",
        "graph_label": "Topic",
    },
}

# Subtypes per entity type
ENTITY_SUBTYPES: Dict[str, List[str]] = {
    "MK": ["current_mk", "former_mk", "minister", "committee_chair",
            "coalition_chair", "opposition_leader", "speaker"],
    "Faction": ["coalition", "opposition"],
    "Bill": ["government_bill", "private_bill", "committee_bill"],
    "Committee": ["standing", "special", "inquiry", "subcommittee"],
    "BudgetLine": ["ministry", "program", "sub_program", "line_item"],
    "BudgetSupport": ["grant", "tender", "subsidy"],
    "Organization": ["party", "ngo", "yeshiva", "media", "business",
                      "council", "foundation", "lobby", "ministry"],
    "Person": ["rabbi", "businessman", "activist", "academic",
               "civil_servant", "journalist"],
    "Location": ["settlement", "city", "region", "outpost"],
    "Law": ["basic_law", "statute", "amendment", "regulation"],
    "Protocol": ["plenum_session", "committee_session"],
    "Topic": ["security", "economy", "education", "religion",
              "social", "settlements", "foreign_policy", "justice",
              "health", "environment", "technology", "culture"],
}


# ---------------------------------------------------------------------------
# Relationship type definitions
# ---------------------------------------------------------------------------

@dataclass
class RelationType:
    """Definition of a typed relationship in the Knesset graph."""
    name: str
    label_he: str
    label_en: str
    source_types: List[str]  # valid source entity types
    target_types: List[str]  # valid target entity types
    directed: bool = True


RELATIONSHIP_TYPES: Dict[str, RelationType] = {
    "MEMBER_OF": RelationType(
        "MEMBER_OF", "חבר ב", "Member of",
        ["MK"], ["Faction", "Committee", "Organization"],
    ),
    "PROPOSED": RelationType(
        "PROPOSED", "הציע", "Proposed",
        ["MK"], ["Bill"],
    ),
    "VOTED_FOR": RelationType(
        "VOTED_FOR", "הצביע בעד", "Voted for",
        ["MK"], ["Bill"],
    ),
    "VOTED_AGAINST": RelationType(
        "VOTED_AGAINST", "הצביע נגד", "Voted against",
        ["MK"], ["Bill"],
    ),
    "ABSTAINED": RelationType(
        "ABSTAINED", "נמנע", "Abstained",
        ["MK"], ["Bill"],
    ),
    "SPOKE_ABOUT": RelationType(
        "SPOKE_ABOUT", "דיבר על", "Spoke about",
        ["MK"], ["Topic", "Bill", "BudgetLine"],
    ),
    "SITS_ON": RelationType(
        "SITS_ON", "חבר בוועדה", "Sits on",
        ["MK"], ["Committee"],
    ),
    "CHAIRS": RelationType(
        "CHAIRS", "יושב ראש", "Chairs",
        ["MK"], ["Committee", "Faction"],
    ),
    "LEADS": RelationType(
        "LEADS", "מנהיג", "Leads",
        ["MK", "Person"], ["Faction", "Organization"],
    ),
    "FUNDED_BY": RelationType(
        "FUNDED_BY", "ממומן ע\"י", "Funded by",
        ["Organization", "Person"], ["BudgetLine", "BudgetSupport"],
    ),
    "RECEIVES_SUPPORT": RelationType(
        "RECEIVES_SUPPORT", "מקבל תמיכה", "Receives support",
        ["Organization"], ["BudgetSupport"],
    ),
    "LOBBIED_BY": RelationType(
        "LOBBIED_BY", "מושפע ע\"י", "Lobbied by",
        ["MK"], ["Organization", "Person"],
    ),
    "AMENDS": RelationType(
        "AMENDS", "מתקן", "Amends",
        ["Bill"], ["Law"],
    ),
    "DISCUSSED_IN": RelationType(
        "DISCUSSED_IN", "נדון ב", "Discussed in",
        ["Bill", "Topic"], ["Committee"],
    ),
    "MENTIONED_IN": RelationType(
        "MENTIONED_IN", "מוזכר ב", "Mentioned in",
        ["MK", "Bill", "Organization", "Topic"], ["Protocol"],
    ),
    "BUDGET_UNDER": RelationType(
        "BUDGET_UNDER", "תחת סעיף", "Budget under",
        ["BudgetLine"], ["BudgetLine"],
    ),
    "SUPPORTS_TOPIC": RelationType(
        "SUPPORTS_TOPIC", "תומך ב", "Supports",
        ["MK", "Faction"], ["Topic"],
    ),
    "OPPOSES_TOPIC": RelationType(
        "OPPOSES_TOPIC", "מתנגד ל", "Opposes",
        ["MK", "Faction"], ["Topic"],
    ),
    "COALITION_AGREEMENT": RelationType(
        "COALITION_AGREEMENT", "הסכם קואליציוני", "Coalition agreement",
        ["Faction"], ["Topic"],
    ),
    "FAMILY_TIE": RelationType(
        "FAMILY_TIE", "קשר משפחתי", "Family tie",
        ["MK"], ["Person"],
        directed=False,
    ),
    "ALLIED_WITH": RelationType(
        "ALLIED_WITH", "בברית עם", "Allied with",
        ["MK", "Faction"], ["MK", "Faction"],
        directed=False,
    ),
    "RELATED_TO": RelationType(
        "RELATED_TO", "קשור ל", "Related to",
        list(ENTITY_TYPES.keys()), list(ENTITY_TYPES.keys()),
        directed=False,
    ),
}


# ---------------------------------------------------------------------------
# Topic taxonomy — Knesset domain topics
# ---------------------------------------------------------------------------

KNESSET_TOPICS: Dict[str, Dict[str, str]] = {
    "security": {"he": "ביטחון", "en": "Security & Defense"},
    "economy": {"he": "כלכלה", "en": "Economy & Finance"},
    "education": {"he": "חינוך", "en": "Education"},
    "religion": {"he": "דת ומדינה", "en": "Religion & State"},
    "social": {"he": "חברה ורווחה", "en": "Social Welfare"},
    "settlements": {"he": "התנחלויות", "en": "Settlements"},
    "foreign_policy": {"he": "מדיניות חוץ", "en": "Foreign Policy"},
    "justice": {"he": "משפט", "en": "Justice & Law"},
    "health": {"he": "בריאות", "en": "Health"},
    "environment": {"he": "סביבה", "en": "Environment"},
    "technology": {"he": "טכנולוגיה", "en": "Technology"},
    "culture": {"he": "תרבות", "en": "Culture & Sports"},
    "housing": {"he": "דיור", "en": "Housing"},
    "transportation": {"he": "תחבורה", "en": "Transportation"},
    "immigration": {"he": "עלייה וקליטה", "en": "Immigration"},
    "labor": {"he": "עבודה ותעסוקה", "en": "Labor"},
    "agriculture": {"he": "חקלאות", "en": "Agriculture"},
}

# Keywords for topic classification from Hebrew text
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "security": ["ביטחון", "צבא", "צה\"ל", "מודיעין", "טרור", "גבול", "מלחמה",
                  "הגנה", "נשק", "חמאס", "חיזבאללה", "איראן", "גדר", "כיפת ברזל"],
    "economy": ["תקציב", "כלכלה", "מס", "מיסוי", "בנק", "ריבית", "אינפלציה",
                 "תעסוקה", "שכר", "מינימום", "יוקר", "מחירים", "עלות"],
    "education": ["חינוך", "בית ספר", "תלמידים", "מורים", "אוניברסיטה", "לימודים",
                   "תוכנית לימודים", "ליב\"ה", "בגרות"],
    "religion": ["דת", "רבנות", "כשרות", "שבת", "גיור", "חרדי", "דתי",
                  "כותל", "הר הבית", "נישואין"],
    "social": ["רווחה", "ביטוח לאומי", "עוני", "פנסיה", "נכות", "קשישים",
                "שוויון", "אפליה"],
    "settlements": ["התנחלות", "יהודה ושומרון", "מתנחלים", "בנייה", "הסדרה",
                     "מאחז", "ריבונות"],
    "health": ["בריאות", "בית חולים", "רפואה", "תרופות", "קופת חולים",
                "רופאים", "אחיות"],
    "justice": ["משפט", "בית משפט", "שופט", "פרקליט", "חוקה", "בג\"ץ",
                 "עבירה", "עונש"],
    "housing": ["דיור", "דירה", "בנייה", "משכנתא", "שכירות", "תמ\"א",
                 "פינוי בינוי"],
    "transportation": ["תחבורה", "רכבת", "כביש", "מטרו", "אוטובוס",
                         "נתיבי ישראל"],
}


# ---------------------------------------------------------------------------
# Pinecone namespace configuration
# ---------------------------------------------------------------------------

PINECONE_NAMESPACES = {
    "protocols": "Knesset protocol speeches and debates",
    "bills": "Bill text and summaries",
    "budgets": "Budget descriptions and support details",
    "entities": "Entity descriptions (MKs, orgs, etc.)",
    "news": "News articles and media coverage",
}


# ---------------------------------------------------------------------------
# Collection source registry
# ---------------------------------------------------------------------------

COLLECTION_SOURCES: Dict[str, Dict[str, any]] = {
    "obudget:budgets": {
        "priority": 1,
        "interval_seconds": 86400,
        "collector_class": "OBudgetCollector",
        "description_he": "תקציב המדינה",
    },
    "obudget:supports": {
        "priority": 1,
        "interval_seconds": 86400,
        "collector_class": "OBudgetCollector",
        "description_he": "תמיכות ממשלתיות",
    },
    "obudget:tenders": {
        "priority": 1,
        "interval_seconds": 86400,
        "collector_class": "OBudgetCollector",
        "description_he": "מכרזים ממשלתיים",
    },
    "knesset:protocols": {
        "priority": 1,
        "interval_seconds": 43200,
        "collector_class": "ProtocolCollector",
        "description_he": "דברי הכנסת",
    },
    "knesset:odata:members": {
        "priority": 2,
        "interval_seconds": 86400,
        "collector_class": "KnessetMemberCollector",
        "description_he": "חברי כנסת",
    },
    "knesset:odata:bills": {
        "priority": 2,
        "interval_seconds": 43200,
        "collector_class": "KnessetBillCollector",
        "description_he": "הצעות חוק",
    },
    "knesset:odata:votes": {
        "priority": 2,
        "interval_seconds": 43200,
        "collector_class": "KnessetVoteCollector",
        "description_he": "הצבעות",
    },
    "knesset:odata:committees": {
        "priority": 2,
        "interval_seconds": 86400,
        "collector_class": "KnessetCommitteeCollector",
        "description_he": "ועדות הכנסת",
    },
    "oknesset:api": {
        "priority": 2,
        "interval_seconds": 86400,
        "collector_class": "OKnessetCollector",
        "description_he": "כנסת פתוחה",
    },
    "hasadna:pipelines": {
        "priority": 2,
        "interval_seconds": 604800,
        "collector_class": "HasadnaCollector",
        "description_he": "הסדנא לידע ציבורי",
    },
    "datagov:datasets": {
        "priority": 3,
        "interval_seconds": 604800,
        "collector_class": "DataGovCollector",
        "description_he": "מאגר נתונים ממשלתי",
    },
    "guidestar:ngos": {
        "priority": 3,
        "interval_seconds": 604800,
        "collector_class": "GuideStar collector",
        "description_he": "גיידסטאר - עמותות",
    },
    "kolzchut:laws": {
        "priority": 3,
        "interval_seconds": 604800,
        "collector_class": "KolZchutCollector",
        "description_he": "כל זכות",
    },
    "knesset:research": {
        "priority": 3,
        "interval_seconds": 604800,
        "collector_class": "KnessetResearchCollector",
        "description_he": "מרכז המחקר והמידע",
    },
    "rzmapper:sync": {
        "priority": 2,
        "interval_seconds": 21600,  # every 6 hours
        "collector_class": "RZMapperSyncCollector",
        "description_he": "סנכרון ישויות מ-RZMAPPER",
    },
}
