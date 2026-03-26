"""Hebrew NLP module for entity extraction and text analysis.

Knesset-domain Hebrew NLP — no external Hebrew NLP libraries needed.
Uses regex + rules + dictionary lookup.  Optionally loads known entities
from a GraphStorage instance so MK / faction names can be recognized
in free-text queries and speeches.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..graph_storage import GraphStorage


# ---------------------------------------------------------------------------
# Hebrew month name → Gregorian month number
# ---------------------------------------------------------------------------

_HEBREW_MONTHS_GREG: Dict[str, int] = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3,
    "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9,
    "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}

# Hebrew calendar month names (not converted — kept as labels only)
_HEBREW_MONTHS_HEB: List[str] = [
    "תשרי", "חשוון", "כסלו", "טבת", "שבט", "אדר",
    "אדר א", "אדר ב", "ניסן", "אייר", "סיוון",
    "תמוז", "אב", "אלול",
]

# Gematria lookup for Hebrew date day numbers (כ' = 20, etc.)
_GEMATRIA: Dict[str, int] = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5,
    "ו": 6, "ז": 7, "ח": 8, "ט": 9, "י": 10,
    "כ": 20, "ל": 30,
}

# ---------------------------------------------------------------------------
# Niqqud / diacritics range for stripping
# ---------------------------------------------------------------------------

_NIQQUD_RE = re.compile(r"[\u0591-\u05C7]")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# "15 בינואר 2026"
_DATE_GREG_HE = re.compile(
    r"(\d{1,2})\s+ב?("
    + "|".join(_HEBREW_MONTHS_GREG.keys())
    + r")\s+(\d{4})"
)

# "כ' בטבת" (Hebrew calendar — capture as-is, no conversion)
_DATE_HEB_CAL = re.compile(
    r"""([\u05d0-\u05ea]{1,2})['׳]\s+ב?("""
    + "|".join(_HEBREW_MONTHS_HEB)
    + r")"
)

# Number with optional comma separators
_NUMBER_RE = re.compile(r"\b(\d[\d,]*)\b")

# ח"כ prefix (Member of Knesset abbreviation)
_MK_PREFIX_RE = re.compile(r'ח"כ\s+')

# Common abbreviation patterns to keep together
_ABBREV_RE = re.compile(r'([\u05d0-\u05ea])"([\u05d0-\u05ea])')


class HebrewNLP:
    """Knesset-domain Hebrew NLP — entity extraction and text analysis."""

    # ------------------------------------------------------------------
    # Known entity dictionaries (populated from graph data)
    # ------------------------------------------------------------------
    MK_NAMES: Dict[str, str] = {}          # name_he → mk_id
    FACTION_NAMES: Dict[str, str] = {}     # name_he → faction_id

    BILL_KEYWORDS: List[str] = [
        "חוק", "הצעת חוק", "חוק יסוד", "תקנות", "צו",
        "תיקון", "חוק חסינות", "חוק מיסוי",
    ]

    POLITICAL_TERMS: Dict[str, str] = {
        "קואליציה": "coalition",
        "אופוזיציה": "opposition",
        "מליאה": "plenum",
        "ועדה": "committee",
        "הצבעה": "vote",
        "קריאה ראשונה": "first_reading",
        "קריאה שנייה": "second_reading",
        "קריאה שלישית": "third_reading",
        "קריאה טרומית": "preliminary_reading",
        "ועדת כנסת": "knesset_committee",
        "ועדת חוקה": "constitution_committee",
        "ועדת כספים": "finance_committee",
        "ועדת חוץ וביטחון": "foreign_affairs_committee",
        "רוב מיוחד": "special_majority",
        "הסכם קואליציוני": "coalition_agreement",
        "אי אמון": "no_confidence",
        "הצבעת אמון": "confidence_vote",
        "פיזור הכנסת": "dissolve_knesset",
        "חסינות": "immunity",
        "יו\"ר": "chairman",
        "ראש הממשלה": "prime_minister",
        "שר": "minister",
        "סגן שר": "deputy_minister",
    }

    # Sentiment / stance keywords
    _PRO_KEYWORDS: List[str] = [
        "בעד", "תומך", "מוכן", "מסכים", "אצביע בעד",
        "תומכים", "מאשר", "נתמוך", "אני בעד", "מצדד",
    ]
    _CON_KEYWORDS: List[str] = [
        "נגד", "מתנגד", "דוחה", "אתנגד", "אצביע נגד",
        "מתנגדים", "נתנגד", "מסרב", "לא מסכים", "שולל",
    ]
    _STRONG_PRO: List[str] = ["בהחלט בעד", "תמיכה מלאה", "ללא סייג"]
    _STRONG_CON: List[str] = ["מתנגד נחרצות", "בשום פנים", "התנגדות מוחלטת"]

    # Vote intent patterns
    _VOTE_PRO_RE = re.compile(
        r"(אצביע\s+בעד|אני\s+בעד|נצביע\s+בעד|אתמוך)", re.UNICODE
    )
    _VOTE_CON_RE = re.compile(
        r"(אצביע\s+נגד|אני\s+נגד|נצביע\s+נגד|אתנגד)", re.UNICODE
    )
    _VOTE_ABSTAIN_RE = re.compile(
        r"(אנמנע|אמנע\s+מהצבעה|נמנע)", re.UNICODE
    )

    def __init__(self, graph_storage: Optional[GraphStorage] = None) -> None:
        # Instance-level copies so mutations don't affect class
        self.MK_NAMES = dict(self.__class__.MK_NAMES)
        self.FACTION_NAMES = dict(self.__class__.FACTION_NAMES)
        if graph_storage is not None:
            self.load_entities_from_graph(graph_storage)

    # ------------------------------------------------------------------
    # Entity loading
    # ------------------------------------------------------------------

    def load_entities_from_graph(self, graph_storage: GraphStorage) -> None:
        """Populate MK_NAMES and FACTION_NAMES from graph nodes."""
        for node in graph_storage.list_nodes(label="MK"):
            name = node.get("name", "")
            node_id = node.get("id", "")
            if name and node_id:
                self.MK_NAMES[name] = node_id
        for node in graph_storage.list_nodes(label="Faction"):
            name = node.get("name", "")
            node_id = node.get("id", "")
            if name and node_id:
                self.FACTION_NAMES[name] = node_id

    # ------------------------------------------------------------------
    # Main extraction
    # ------------------------------------------------------------------

    def extract_entities(self, text_he: str) -> Dict[str, Any]:
        """Extract all recognized entities from Hebrew text.

        Returns dict with keys:
          mk_mentions, faction_mentions, bill_mentions,
          political_terms, dates, numbers
        """
        clean = self._strip_niqqud(text_he)

        return {
            "mk_mentions": self._extract_mk_mentions(clean),
            "faction_mentions": self._extract_faction_mentions(clean),
            "bill_mentions": self._extract_bill_mentions(clean),
            "political_terms": self._extract_political_terms(clean),
            "dates": self.detect_hebrew_dates(clean),
            "numbers": self._extract_numbers(clean),
        }

    # ------------------------------------------------------------------
    # MK mentions
    # ------------------------------------------------------------------

    def _extract_mk_mentions(self, text: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        # Check ח"כ prefix mentions first
        for m in _MK_PREFIX_RE.finditer(text):
            start = m.end()
            # Grab next 2-4 Hebrew words after ח"כ
            rest = text[start:]
            name_match = re.match(
                r"([\u05d0-\u05ea\-]+(?:\s+[\u05d0-\u05ea\-]+){0,3})", rest
            )
            if name_match:
                candidate = name_match.group(1).strip()
                mk_id = self.MK_NAMES.get(candidate)
                results.append({
                    "name": candidate,
                    "mk_id": mk_id,
                    "position_in_text": m.start(),
                })
        # Direct dictionary lookup for all known names
        for name, mk_id in self.MK_NAMES.items():
            idx = text.find(name)
            if idx >= 0 and not any(r["mk_id"] == mk_id for r in results):
                results.append({
                    "name": name,
                    "mk_id": mk_id,
                    "position_in_text": idx,
                })
        return results

    # ------------------------------------------------------------------
    # Faction mentions
    # ------------------------------------------------------------------

    def _extract_faction_mentions(self, text: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for name, fid in self.FACTION_NAMES.items():
            if name in text:
                results.append({"name": name, "faction_id": fid})
        return results

    # ------------------------------------------------------------------
    # Bill mentions
    # ------------------------------------------------------------------

    def _extract_bill_mentions(self, text: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for kw in self.BILL_KEYWORDS:
            if kw in text:
                # Try to grab the phrase around the keyword
                idx = text.find(kw)
                context_start = max(0, idx - 5)
                context_end = min(len(text), idx + len(kw) + 60)
                snippet = text[context_start:context_end].strip()
                results.append({
                    "title": snippet,
                    "keywords_found": [kw],
                })
        # Deduplicate by merging overlapping snippets
        if len(results) > 1:
            merged: List[Dict[str, Any]] = [results[0]]
            for r in results[1:]:
                if r["title"] in merged[-1]["title"]:
                    merged[-1]["keywords_found"].extend(r["keywords_found"])
                else:
                    merged.append(r)
            return merged
        return results

    # ------------------------------------------------------------------
    # Political terms
    # ------------------------------------------------------------------

    def _extract_political_terms(self, text: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        # Check longer terms first to avoid partial matches
        sorted_terms = sorted(
            self.POLITICAL_TERMS.items(), key=lambda t: -len(t[0])
        )
        found_spans: List[tuple] = []
        for term_he, term_en in sorted_terms:
            idx = text.find(term_he)
            if idx >= 0:
                span = (idx, idx + len(term_he))
                # Skip if covered by a longer term already found
                if any(s[0] <= span[0] and s[1] >= span[1] for s in found_spans):
                    continue
                found_spans.append(span)
                # Extract ~30 chars of context around the term
                ctx_start = max(0, idx - 15)
                ctx_end = min(len(text), idx + len(term_he) + 15)
                results.append({
                    "term": term_he,
                    "english": term_en,
                    "context": text[ctx_start:ctx_end].strip(),
                })
        return results

    # ------------------------------------------------------------------
    # Numbers
    # ------------------------------------------------------------------

    def _extract_numbers(self, text: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for m in _NUMBER_RE.finditer(text):
            raw = m.group(1).replace(",", "")
            try:
                value = int(raw)
            except ValueError:
                continue
            # Grab context around the number
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            results.append({
                "value": value,
                "context": text[start:end].strip(),
            })
        return results

    # ------------------------------------------------------------------
    # Bill topic extraction
    # ------------------------------------------------------------------

    def extract_bill_topic(self, text_he: str) -> Dict[str, Any]:
        """From a user question, extract topic, action, and constraints.

        Returns:
            {"topic": str, "action": str, "constraints": list[str]}
        """
        clean = self._strip_niqqud(text_he)

        # Action verbs
        action = ""
        action_patterns = [
            (r"להעביר\s+חוק", "להעביר חוק"),
            (r"להצביע\s+על", "להצביע"),
            (r"להציע\s+חוק", "להציע חוק"),
            (r"לתקן\s+חוק", "לתקן חוק"),
            (r"לבטל\s+חוק", "לבטל חוק"),
            (r"להקים\s+ועדה", "להקים ועדה"),
        ]
        for pattern, label in action_patterns:
            if re.search(pattern, clean):
                action = label
                break

        # Constraints: "בלי X", "ללא X", "בתנאי ש"
        constraints: List[str] = []
        for m in re.finditer(r"(?:בלי|ללא)\s+([\u05d0-\u05ea\s]+?)(?:\s*[,.]|$)", clean):
            constraints.append(m.group(1).strip())
        for m in re.finditer(r"בתנאי\s+ש([\u05d0-\u05ea\s]+?)(?:\s*[,.]|$)", clean):
            constraints.append(m.group(1).strip())

        # Topic: the longest Hebrew noun-phrase after removing action/constraint
        topic = clean
        # Remove action phrase
        for _, label in action_patterns:
            topic = topic.replace(label, "")
        # Remove constraint phrases
        for c in constraints:
            topic = topic.replace(c, "")
        # Remove common filler
        for filler in ["בלי", "ללא", "בתנאי ש", "האם", "אפשר", "מה", "איך"]:
            topic = topic.replace(filler, "")
        topic = re.sub(r"\s+", " ", topic).strip()

        return {
            "topic": topic,
            "action": action,
            "constraints": constraints,
        }

    # ------------------------------------------------------------------
    # Stance classification
    # ------------------------------------------------------------------

    def classify_political_stance(self, text_he: str) -> str:
        """Classify text stance:
        "בעד_חזק" | "בעד" | "ניטרלי" | "נגד" | "נגד_חזק"
        """
        clean = self._strip_niqqud(text_he).lower()

        # Strong matches first
        for kw in self._STRONG_PRO:
            if kw in clean:
                return "בעד_חזק"
        for kw in self._STRONG_CON:
            if kw in clean:
                return "נגד_חזק"

        pro_score = sum(1 for kw in self._PRO_KEYWORDS if kw in clean)
        con_score = sum(1 for kw in self._CON_KEYWORDS if kw in clean)

        if pro_score > con_score:
            return "בעד"
        if con_score > pro_score:
            return "נגד"
        return "ניטרלי"

    # ------------------------------------------------------------------
    # Hebrew date detection
    # ------------------------------------------------------------------

    def detect_hebrew_dates(self, text_he: str) -> List[Dict[str, Any]]:
        """Parse Hebrew date formats and return structured results."""
        results: List[Dict[str, Any]] = []
        clean = self._strip_niqqud(text_he)

        # Gregorian dates in Hebrew: "15 בינואר 2026"
        for m in _DATE_GREG_HE.finditer(clean):
            day, month_he, year = int(m.group(1)), m.group(2), int(m.group(3))
            month_num = _HEBREW_MONTHS_GREG.get(month_he, 0)
            if 1 <= month_num <= 12 and 1 <= day <= 31:
                try:
                    parsed = date(year, month_num, day)
                    results.append({
                        "date_str": m.group(0),
                        "parsed_date": parsed.isoformat(),
                    })
                except ValueError:
                    results.append({
                        "date_str": m.group(0),
                        "parsed_date": None,
                    })

        # Hebrew calendar dates: "כ' בטבת" (kept as string, no conversion)
        for m in _DATE_HEB_CAL.finditer(clean):
            results.append({
                "date_str": m.group(0),
                "parsed_date": None,  # Hebrew calendar — no Gregorian conversion
            })

        # Relative dates
        today = date.today()
        relative_map: Dict[str, date] = {
            "היום": today,
            "מחר": today + timedelta(days=1),
            "מחרתיים": today + timedelta(days=2),
            "אתמול": today - timedelta(days=1),
            "שלשום": today - timedelta(days=2),
        }
        for word, d in relative_map.items():
            if word in clean:
                results.append({
                    "date_str": word,
                    "parsed_date": d.isoformat(),
                })

        return results

    # ------------------------------------------------------------------
    # Tokenizer
    # ------------------------------------------------------------------

    def tokenize_hebrew(self, text_he: str) -> List[str]:
        """Simple Hebrew tokenizer.

        - Strips niqqud
        - Preserves abbreviations: ח"כ, ת"ל, מ"כ etc.
        - Splits on spaces and punctuation
        """
        clean = self._strip_niqqud(text_he)
        # Protect abbreviations by replacing " with placeholder
        protected = _ABBREV_RE.sub(r"\1\u0000\2", clean)
        # Split on non-Hebrew, non-digit, non-placeholder
        tokens = re.findall(r'[\u05d0-\u05ea\u0000\d]+', protected)
        # Restore abbreviation mark
        return [t.replace("\u0000", '"') for t in tokens if t]

    # ------------------------------------------------------------------
    # Text similarity
    # ------------------------------------------------------------------

    def compute_text_similarity(self, text_a: str, text_b: str) -> float:
        """Jaccard similarity on Hebrew tokens. Returns 0.0–1.0."""
        tokens_a = set(self.tokenize_hebrew(text_a))
        tokens_b = set(self.tokenize_hebrew(text_b))
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union) if union else 0.0

    # ------------------------------------------------------------------
    # Vote intent
    # ------------------------------------------------------------------

    def extract_vote_intent(self, text_he: str) -> Optional[str]:
        """Detect voting intent from MK speech text.

        Returns "בעד", "נגד", "נמנע", or None if unclear.
        """
        clean = self._strip_niqqud(text_he)
        if self._VOTE_PRO_RE.search(clean):
            return "בעד"
        if self._VOTE_CON_RE.search(clean):
            return "נגד"
        if self._VOTE_ABSTAIN_RE.search(clean):
            return "נמנע"
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_niqqud(text: str) -> str:
        """Remove Hebrew niqqud (vowel points) from text."""
        return _NIQQUD_RE.sub("", text)
