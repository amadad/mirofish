"""RZMapper Bridge — imports RZMAPPER entity data into MiroFish KnessetPersona.

Reads person entities from the RZMAPPER graph project, converts them to
KnessetPersona dataclasses, and enriches them with relationship context,
budget-derived policy stances, and social-media feed snippets.

Data sources (all read-only):
- RZMAPPER/data/entities/person_*.json  — entity files
- RZMAPPER/dashboard/public/data/snapshot.json — graph snapshot (edges)
- RZMAPPER/data/raw/budget/ — Open Budget API results
- RZMAPPER/data/raw/telegram/ — Telegram channel messages
- Neo4j bolt://localhost:7687 (optional, graceful fallback)
"""

from __future__ import annotations

import glob
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import KnessetPersona

logger = logging.getLogger("mirofish.knesset.rzmapper_bridge")

# ---------------------------------------------------------------------------
# Default RZMAPPER location & coalition config
# ---------------------------------------------------------------------------

_DEFAULT_RZMAPPER_DIR = "C:/Users/markb/Documents/MyVault/MarkSpaceIt/RZMAPPER"

_COALITION_FACTIONS = [
    "ליכוד", 'ש"ס', "יהדות התורה", "הציונות הדתית", "עוצמה יהודית", "נועם",
]

_OPPOSITION_FACTIONS = [
    "יש עתיד", "מחנה ממלכתי", "ישראל ביתנו", "העבודה",
    "הרשימה המשותפת", 'רע"ם', 'בל"ד',
]

# Faction → rhetoric_style heuristic
_RHETORIC_MAP: Dict[str, str] = {
    "ליכוד": "technocrat",
    "מחנה ממלכתי": "technocrat",
    "יש עתיד": "technocrat",
    "ישראל ביתנו": "populist",
    "העבודה": "technocrat",
    'ש"ס': "ideologue",
    "יהדות התורה": "ideologue",
    "הציונות הדתית": "ideologue",
    "עוצמה יהודית": "populist",
    "נועם": "ideologue",
    "הרשימה המשותפת": "populist",
    'רע"ם': "technocrat",
    'בל"ד': "populist",
}

# Relationship type → Hebrew label for context summaries
_REL_LABELS: Dict[str, str] = {
    "ally": "בעל ברית עם",
    "rival": "מתנגד ל",
    "related_to": "קשור ל",
    "member_of": "חבר ב",
    "leads": "מנהיג את",
    "funds": "ממן את",
    "funded_by": "ממומן ע\"י",
    "opposes": "מתנגד ל",
    "supports": "תומך ב",
    "coalition_partner": "שותף קואליציוני עם",
}


class RZMapperBridge:
    """Bridge between RZMAPPER entity store and MiroFish KnessetPersona.

    Parameters
    ----------
    rzmapper_data_dir : str or None
        Root directory of RZMAPPER project.  Falls back to the
        ``RZMAPPER_DIR`` environment variable or the hard-coded default.
    rzmapper_neo4j_uri : str or None
        Neo4j Bolt URI (e.g. ``bolt://localhost:7687``).  When provided
        *and* the ``neo4j`` package is installed, relationship queries use
        Cypher instead of the snapshot file.
    """

    def __init__(
        self,
        rzmapper_data_dir: Optional[str] = None,
        rzmapper_neo4j_uri: Optional[str] = None,
    ) -> None:
        self._root = Path(
            rzmapper_data_dir
            or os.environ.get("RZMAPPER_DIR", _DEFAULT_RZMAPPER_DIR)
        )
        self._entities_dir = self._root / "data" / "entities"
        self._snapshot_path = self._root / "dashboard" / "public" / "data" / "snapshot.json"
        self._budget_dir = self._root / "data" / "raw" / "budget"
        self._telegram_dir = self._root / "data" / "raw" / "telegram"
        self._neo4j_uri = rzmapper_neo4j_uri

        # Lazy-loaded caches
        self._snapshot: Optional[Dict[str, Any]] = None
        self._neo4j_driver: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_entities(self) -> List[KnessetPersona]:
        """Read all person_*.json from RZMAPPER and convert to KnessetPersona.

        Filters for politicians/MKs: ``subtype == "politician"`` **or**
        ``description_he`` contains ``"חבר כנסת"``.

        Returns
        -------
        list[KnessetPersona]
            Converted personas, sorted by influence_score descending.
        """
        personas: List[KnessetPersona] = []
        pattern = str(self._entities_dir / "person_*.json")
        files = glob.glob(pattern)

        if not files:
            logger.warning("אין קבצי ישויות ב-%s", self._entities_dir)
            return personas

        logger.info("סורק %d קבצי ישויות מ-RZMAPPER", len(files))

        for fpath in files:
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    entity = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("שגיאה בקריאת %s: %s", fpath, exc)
                continue

            if not self._is_mk_entity(entity):
                continue

            persona = self._entity_to_persona(entity)
            if persona is not None:
                personas.append(persona)

        personas.sort(key=lambda p: p.influence_score, reverse=True)
        logger.info("סונכרנו %d פרסונות מ-RZMAPPER", len(personas))
        return personas

    def build_relationship_context(self, mk_id: str) -> str:
        """Build a Hebrew text summary of an MK's relationships.

        Tries Neo4j first (if URI + driver available), falls back to
        ``snapshot.json`` edge list.

        Parameters
        ----------
        mk_id : str
            Entity ID (e.g. ``"wikidata_Q1159122"``).

        Returns
        -------
        str
            Hebrew relationship summary, e.g.
            ``"בעל ברית עם גדעון סער, מתנגד לאיתמר בן גביר"``
        """
        # Try Neo4j first
        context = self._neo4j_relationships(mk_id)
        if context:
            return context

        # Fallback: snapshot.json
        return self._snapshot_relationships(mk_id)

    def get_budget_positions(self, mk_id: str) -> Dict[str, str]:
        """Infer policy positions from Open Budget data.

        Reads budget result files and maps budget categories the MK's
        party supports to topic stances.

        Parameters
        ----------
        mk_id : str
            Entity ID of the MK.

        Returns
        -------
        dict[str, str]
            Mapping of topic → stance (e.g. ``{"חינוך": "בעד_הגדלה"}``).
            Empty dict on error or missing data.
        """
        stances: Dict[str, str] = {}

        budget_file = self._budget_dir / "open_budget_results.json"
        if not budget_file.exists():
            logger.debug("אין נתוני תקציב ב-%s", budget_file)
            return stances

        try:
            with open(budget_file, "r", encoding="utf-8") as fh:
                budget_data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("שגיאה בקריאת נתוני תקציב: %s", exc)
            return stances

        if not isinstance(budget_data, list) or not budget_data:
            return stances

        # Resolve the MK's party from entities
        party = self._resolve_party(mk_id)
        if not party:
            return stances

        # Map budget categories to stances based on party support
        _BUDGET_TOPIC_MAP = {
            "חינוך": "חינוך",
            "ביטחון": "ביטחון_לאומי",
            "בריאות": "בריאות",
            "רווחה": "רווחה",
            "תחבורה": "תשתיות",
            "שיכון": "דיור",
            "התיישבות": "התנחלויות",
            "דת": "דת_ומדינה",
        }

        for item in budget_data:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            for keyword, topic in _BUDGET_TOPIC_MAP.items():
                if keyword in title:
                    # Coalition parties generally support budget items
                    if party in _COALITION_FACTIONS:
                        stances[topic] = "בעד_הגדלה"
                    else:
                        stances[topic] = "בעד_פיקוח"
                    break

        return stances

    def get_social_feed(
        self, mk_ids: List[str], since_hours: int = 24
    ) -> str:
        """Read Telegram channel messages mentioning given MKs.

        Parameters
        ----------
        mk_ids : list[str]
            Entity IDs to search for.
        since_hours : int
            Only include messages from the last N hours.

        Returns
        -------
        str
            Formatted Hebrew text for prompt injection.
            Empty string if no relevant messages found.
        """
        if not self._telegram_dir.exists():
            logger.debug("תיקיית טלגרם לא נמצאה: %s", self._telegram_dir)
            return ""

        # Resolve names from entity IDs
        names = self._resolve_names(mk_ids)
        if not names:
            return ""

        cutoff = datetime.now(timezone.utc).timestamp() - (since_hours * 3600)
        relevant: List[Dict[str, Any]] = []

        tg_files = glob.glob(str(self._telegram_dir / "*.json"))
        for fpath in tg_files:
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    messages = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(messages, list):
                continue

            for msg in messages:
                text = msg.get("text", "")
                date_str = msg.get("date", "")
                if not text or not date_str:
                    continue

                # Parse ISO date
                try:
                    msg_dt = datetime.fromisoformat(date_str)
                    if msg_dt.timestamp() < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

                # Check if any MK name appears in the message
                for name in names:
                    if name and name in text:
                        relevant.append({
                            "channel": msg.get("channel_title", msg.get("channel", "")),
                            "text": text[:300],
                            "date": date_str,
                            "views": msg.get("views", 0),
                        })
                        break

        if not relevant:
            return ""

        # Sort by views descending, take top 10
        relevant.sort(key=lambda m: m.get("views", 0), reverse=True)
        relevant = relevant[:10]

        lines = ["--- פיד טלגרם אחרון ---"]
        for msg in relevant:
            lines.append(
                f"[{msg['channel']}] ({msg['date'][:16]}) {msg['text']}"
            )
        lines.append("--- סוף פיד ---")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Entity conversion
    # ------------------------------------------------------------------

    def _entity_to_persona(self, entity: dict) -> Optional[KnessetPersona]:
        """Convert a single RZMAPPER entity dict to KnessetPersona.

        Returns None if the entity is missing required fields (name, id).
        """
        eid = entity.get("id", "")
        name_he = entity.get("name_he", "")
        name_en = entity.get("name_en", "")

        if not eid or (not name_he and not name_en):
            return None

        props = entity.get("properties", {})

        # Faction / party
        faction = props.get("party", "")
        if not faction and isinstance(props.get("parties"), list):
            parties = props["parties"]
            faction = parties[0] if parties else ""

        # Normalise faction for coalition lookup
        faction_normalised = self._normalise_faction(faction)

        # Coalition membership
        coalition_member = faction_normalised in _COALITION_FACTIONS

        # Knesset person ID
        knesset_pid = props.get("knesset_person_id", 0)
        if isinstance(knesset_pid, str):
            try:
                knesset_pid = int(knesset_pid)
            except ValueError:
                knesset_pid = 0

        # Gender
        gender = props.get("gender", "male")
        if isinstance(gender, list):
            gender = gender[0] if gender else "male"

        # Current MK flag
        is_current = props.get("is_current_mk", True)
        if isinstance(is_current, str):
            is_current = is_current.lower() in ("true", "1", "yes")

        # Influence score
        influence = entity.get("influence_score", 50)

        # Rhetoric style heuristic
        rhetoric = _RHETORIC_MAP.get(faction_normalised, "technocrat")

        # Ideology tags from focus_areas
        ideology_tags = entity.get("focus_areas", [])

        # Committee roles from positions
        committee_roles: List[str] = []
        knesset_positions = props.get("knesset_positions", [])
        if isinstance(knesset_positions, list):
            committee_roles = knesset_positions

        # Personality text from description + timeline
        personality = self._build_personality(entity)

        # Agent ID derived from entity ID
        agent_id = f"rz_{eid.replace(' ', '_')}"

        return KnessetPersona(
            agent_id=agent_id,
            name_he=name_he or name_en,
            name_en=name_en or name_he,
            faction=faction,
            faction_id=faction_normalised,
            knesset_person_id=knesset_pid,
            gender=gender,
            is_current_mk=bool(is_current),
            coalition_member=coalition_member,
            influence_score=influence,
            loyalty_score=entity.get("confidence", 0.8),
            ideology_tags=ideology_tags,
            stances={},
            personality=personality,
            rhetoric_style=rhetoric,
            committee_roles=committee_roles,
            voting_history_summary="",
            twitter_handle=props.get("twitter_handle"),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_mk_entity(entity: dict) -> bool:
        """Return True if the entity represents an MK / politician."""
        if entity.get("entity_type") != "person":
            return False
        subtype = entity.get("subtype", "")
        if subtype == "politician":
            return True
        desc = entity.get("description_he", "")
        if "חבר כנסת" in desc or "חברת כנסת" in desc:
            return True
        props = entity.get("properties", {})
        topics = props.get("topics", [])
        if isinstance(topics, list) and "role.pep" in topics:
            return True
        return False

    @staticmethod
    def _normalise_faction(faction: str) -> str:
        """Normalise faction name for coalition lookup.

        Handles common variations (with/without quotes, prefix הליכוד).
        """
        f = faction.strip()
        if f.startswith("הליכוד"):
            return "ליכוד"
        if f.startswith("הליכוד"):
            return "ליכוד"
        return f

    @staticmethod
    def _build_personality(entity: dict) -> str:
        """Generate personality text from description and timeline."""
        parts: List[str] = []
        desc = entity.get("description_he", "")
        if desc:
            parts.append(desc[:200])

        timeline = entity.get("timeline", [])
        if isinstance(timeline, list) and timeline:
            events = [
                f"{t.get('year', '?')}: {t.get('event', '')}"
                for t in timeline[:5]
                if isinstance(t, dict)
            ]
            if events:
                parts.append("אירועים מרכזיים: " + "; ".join(events))

        return " | ".join(parts) if parts else ""

    def _resolve_party(self, mk_id: str) -> str:
        """Resolve an MK's party from their entity file."""
        pattern = str(self._entities_dir / "person_*.json")
        for fpath in glob.glob(pattern):
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    entity = json.load(fh)
                if entity.get("id") == mk_id:
                    return entity.get("properties", {}).get("party", "")
            except (json.JSONDecodeError, OSError):
                continue
        return ""

    def _resolve_names(self, mk_ids: List[str]) -> List[str]:
        """Resolve a list of entity IDs to Hebrew names."""
        names: List[str] = []
        pattern = str(self._entities_dir / "person_*.json")
        id_set = set(mk_ids)

        for fpath in glob.glob(pattern):
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    entity = json.load(fh)
                if entity.get("id") in id_set:
                    name = entity.get("name_he", "")
                    if name:
                        names.append(name)
            except (json.JSONDecodeError, OSError):
                continue
        return names

    def _load_snapshot(self) -> Dict[str, Any]:
        """Load and cache the graph snapshot."""
        if self._snapshot is not None:
            return self._snapshot

        if not self._snapshot_path.exists():
            logger.warning("קובץ snapshot לא נמצא: %s", self._snapshot_path)
            self._snapshot = {"nodes": [], "edges": []}
            return self._snapshot

        try:
            with open(self._snapshot_path, "r", encoding="utf-8") as fh:
                self._snapshot = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("שגיאה בקריאת snapshot: %s", exc)
            self._snapshot = {"nodes": [], "edges": []}

        return self._snapshot

    def _snapshot_relationships(self, mk_id: str) -> str:
        """Build relationship context from snapshot.json edges."""
        snapshot = self._load_snapshot()
        edges = snapshot.get("edges", [])
        nodes = snapshot.get("nodes", [])

        # Build id → name lookup
        name_map: Dict[str, str] = {}
        for node in nodes:
            nid = node.get("id", "")
            name_map[nid] = node.get("name_he", node.get("name_en", nid))

        parts: List[str] = []
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            rel = edge.get("relationship_type", "related_to")

            if src == mk_id:
                label = _REL_LABELS.get(rel, "קשור ל")
                other_name = name_map.get(tgt, tgt)
                parts.append(f"{label}{other_name}")
            elif tgt == mk_id:
                # Reverse relationship
                reverse_label = _REL_LABELS.get(rel, "קשור ל")
                other_name = name_map.get(src, src)
                parts.append(f"{reverse_label}{other_name}")

        if not parts:
            return ""

        return ", ".join(parts[:15])

    def _neo4j_relationships(self, mk_id: str) -> str:
        """Query Neo4j for relationships (optional, graceful fallback)."""
        if not self._neo4j_uri:
            return ""

        try:
            from neo4j import GraphDatabase  # type: ignore[import-untyped]
        except ImportError:
            logger.debug("neo4j package not installed, falling back to snapshot")
            return ""

        try:
            if self._neo4j_driver is None:
                self._neo4j_driver = GraphDatabase.driver(
                    self._neo4j_uri, auth=None
                )

            query = """
            MATCH (a)-[r]-(b)
            WHERE a.id = $mk_id
            RETURN type(r) AS rel_type,
                   b.name_he AS name_he,
                   b.name_en AS name_en,
                   b.id AS other_id
            LIMIT 20
            """
            parts: List[str] = []
            with self._neo4j_driver.session() as session:
                result = session.run(query, mk_id=mk_id)
                for record in result:
                    rel = record["rel_type"].lower()
                    name = record["name_he"] or record["name_en"] or record["other_id"]
                    label = _REL_LABELS.get(rel, "קשור ל")
                    parts.append(f"{label}{name}")

            return ", ".join(parts[:15]) if parts else ""

        except Exception as exc:
            logger.warning("Neo4j query failed, falling back to snapshot: %s", exc)
            return ""
