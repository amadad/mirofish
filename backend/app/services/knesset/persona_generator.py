"""KnessetSim MK Persona Generator.

Generates rich KnessetPersona objects from raw MK entity data (e.g. from
RZMAPPER graph or Knesset OData). Two modes:

1. **LLM-based** (`generate_persona`) — sends Hebrew prompt to LLM via
   LLMRouter with task_type="knesset_persona". Requires explicit approval
   before calling.
2. **Offline** (`generate_persona_offline`) — derives a reasonable persona
   purely from faction/position data using hard-coded heuristic rules.
   No API calls needed.

Both modes produce a fully-populated KnessetPersona dataclass.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import AuxiliaryPersona, KnessetPersona

logger = logging.getLogger("mirofish.knesset.persona_generator")


# ---------------------------------------------------------------------------
# Faction-to-ideology heuristic tables (used by offline generator)
# ---------------------------------------------------------------------------

# Maps faction name substrings (Hebrew) to ideology presets.
# Checked in order; first match wins.
_FACTION_RULES: List[Dict[str, Any]] = [
    # --- Right / Security hawks ---
    {
        "patterns": ["הליכוד", "ליכוד"],
        "ideology_tags": ["ימין", "ביטחוני", "שוק חופשי", "לאומי"],
        "stances": {
            "ביטחון_לאומי": "בעד_חזק",
            "כלכלה": "שוק_חופשי",
            "דת_ומדינה": "מסורתי",
            "הרפורמה_המשפטית": "בעד",
            "שני_מדינות": "נגד",
            "גיוס_חרדים": "ניטרלי",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "שימור",
        },
        "rhetoric_style": "populist",
        "loyalty_base": 0.80,
        "personality_template": "דמות פוליטית לאומנית עם נטייה לשיח ביטחוני ולכלכלת שוק חופשי",
    },
    {
        "patterns": ["הציונות הדתית", "ציונות דתית", "הצהד"],
        "ideology_tags": ["ימין קיצוני", "ציוני-דתי", "ביטחוני", "התנחלויות"],
        "stances": {
            "ביטחון_לאומי": "בעד_חזק",
            "כלכלה": "מעורב",
            "דת_ומדינה": "דתי",
            "הרפורמה_המשפטית": "בעד",
            "שני_מדינות": "נגד_חזק",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "צמצום",
        },
        "rhetoric_style": "ideologue",
        "loyalty_base": 0.85,
        "personality_template": "דמות אידיאולוגית נחושה עם מחויבות עמוקה לציונות הדתית",
    },
    {
        "patterns": ["עוצמה יהודית"],
        "ideology_tags": ["ימין קיצוני", "לאומי", "ביטחוני", "אנטי-ערבי"],
        "stances": {
            "ביטחון_לאומי": "בעד_חזק",
            "כלכלה": "מעורב",
            "דת_ומדינה": "דתי",
            "הרפורמה_המשפטית": "בעד",
            "שני_מדינות": "נגד_חזק",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "צמצום",
        },
        "rhetoric_style": "populist",
        "loyalty_base": 0.75,
        "personality_template": "דמות פרובוקטיבית עם עמדות קיצוניות בנושאי ביטחון וזהות",
    },
    {
        "patterns": ["נעם"],
        "ideology_tags": ["ימין קיצוני", "דתי-חרדי", "שמרני חברתית"],
        "stances": {
            "ביטחון_לאומי": "בעד_חזק",
            "כלכלה": "מעורב",
            "דת_ומדינה": "דתי",
            "הרפורמה_המשפטית": "בעד",
            "שני_מדינות": "נגד_חזק",
            "גיוס_חרדים": "ניטרלי",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "צמצום",
        },
        "rhetoric_style": "ideologue",
        "loyalty_base": 0.85,
        "personality_template": "דמות שמרנית-דתית עם עמדות ערכיות נוקשות",
    },
    # --- Ultra-Orthodox ---
    {
        "patterns": ["ש\"ס", "שס"],
        "ideology_tags": ["חרדי-ספרדי", "דתי", "רווחה חברתית", "שמרני"],
        "stances": {
            "ביטחון_לאומי": "בעד",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "חרדי",
            "הרפורמה_המשפטית": "בעד",
            "שני_מדינות": "ניטרלי",
            "גיוס_חרדים": "נגד_חזק",
            "תקציב_ביטחון": "שימור",
            "זכויות_מיעוטים": "שימור",
        },
        "rhetoric_style": "populist",
        "loyalty_base": 0.90,
        "personality_template": "דמות פוליטית חרדית-ספרדית, מתמקדת בסוגיות רווחה ושמירה על מסורת",
    },
    {
        "patterns": ["יהדות התורה", "דגל התורה", "אגודת ישראל"],
        "ideology_tags": ["חרדי-אשכנזי", "דתי", "אנטי-גיוס", "שמרני"],
        "stances": {
            "ביטחון_לאומי": "ניטרלי",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "חרדי",
            "הרפורמה_המשפטית": "בעד",
            "שני_מדינות": "ניטרלי",
            "גיוס_חרדים": "נגד_חזק",
            "תקציב_ביטחון": "שימור",
            "זכויות_מיעוטים": "שימור",
        },
        "rhetoric_style": "technocrat",
        "loyalty_base": 0.92,
        "personality_template": "דמות חרדית מסורתית, ממוקדת בשמירה על עולם התורה ואוטונומיה קהילתית",
    },
    # --- Center / Center-Left ---
    {
        "patterns": ["יש עתיד"],
        "ideology_tags": ["מרכז", "חילוני", "ליברלי", "פרו-רפורמה"],
        "stances": {
            "ביטחון_לאומי": "בעד",
            "כלכלה": "שוק_חופשי",
            "דת_ומדינה": "חילוני",
            "הרפורמה_המשפטית": "נגד",
            "שני_מדינות": "ניטרלי",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "שימור",
            "זכויות_מיעוטים": "הרחבה",
        },
        "rhetoric_style": "technocrat",
        "loyalty_base": 0.75,
        "personality_template": "דמות מרכזית-ליברלית עם דגש על חינוך, חילוניות ושוויון בנטל",
    },
    {
        "patterns": ["כחול לבן", "מחנה ממלכתי", "ממלכתי"],
        "ideology_tags": ["מרכז", "ביטחוני", "ממלכתי"],
        "stances": {
            "ביטחון_לאומי": "בעד_חזק",
            "כלכלה": "מעורב",
            "דת_ומדינה": "מסורתי",
            "הרפורמה_המשפטית": "נגד",
            "שני_מדינות": "ניטרלי",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "שימור",
        },
        "rhetoric_style": "technocrat",
        "loyalty_base": 0.70,
        "personality_template": "דמות ביטחונית-ממלכתית, פרגמטית, עם רקע צבאי בכיר",
    },
    {
        "patterns": ["ישראל ביתנו"],
        "ideology_tags": ["ימין חילוני", "ביטחוני", "אנטי-חרדי"],
        "stances": {
            "ביטחון_לאומי": "בעד_חזק",
            "כלכלה": "שוק_חופשי",
            "דת_ומדינה": "חילוני",
            "הרפורמה_המשפטית": "ניטרלי",
            "שני_מדינות": "נגד",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "שימור",
        },
        "rhetoric_style": "populist",
        "loyalty_base": 0.65,
        "personality_template": "דמות ימנית-חילונית, קשוחה בנושאי ביטחון ותובענית בנושא גיוס שוויוני",
    },
    # --- Left ---
    {
        "patterns": ["העבודה", "עבודה"],
        "ideology_tags": ["שמאל", "סוציאל-דמוקרטי", "שני מדינות", "רווחה"],
        "stances": {
            "ביטחון_לאומי": "ניטרלי",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "חילוני",
            "הרפורמה_המשפטית": "נגד",
            "שני_מדינות": "בעד",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "שימור",
            "זכויות_מיעוטים": "הרחבה",
        },
        "rhetoric_style": "technocrat",
        "loyalty_base": 0.70,
        "personality_template": "דמות סוציאל-דמוקרטית עם מסורת מפלגתית ארוכה ודגש על שלום ורווחה",
    },
    {
        "patterns": ["מרצ", "מרץ"],
        "ideology_tags": ["שמאל", "שלום", "זכויות אדם", "סביבה"],
        "stances": {
            "ביטחון_לאומי": "נגד",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "חילוני",
            "הרפורמה_המשפטית": "נגד_חזק",
            "שני_מדינות": "בעד_חזק",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "הקטנה",
            "זכויות_מיעוטים": "הרחבה",
        },
        "rhetoric_style": "ideologue",
        "loyalty_base": 0.80,
        "personality_template": "דמות שמאלית-ליברלית עם מחויבות לזכויות אדם, שלום וצדק חברתי",
    },
    # --- Arab parties ---
    {
        "patterns": ["חד\"ש", "חדש", "הרשימה המשותפת"],
        "ideology_tags": ["שמאל", "ערבי-יהודי", "שוויון", "שלום"],
        "stances": {
            "ביטחון_לאומי": "נגד_חזק",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "חילוני",
            "הרפורמה_המשפטית": "נגד",
            "שני_מדינות": "בעד_חזק",
            "גיוס_חרדים": "ניטרלי",
            "תקציב_ביטחון": "הקטנה",
            "זכויות_מיעוטים": "הרחבה",
        },
        "rhetoric_style": "ideologue",
        "loyalty_base": 0.85,
        "personality_template": "דמות פוליטית ערבית-ישראלית הנאבקת למען שוויון אזרחי ופתרון הסכסוך",
    },
    {
        "patterns": ["בל\"ד", "בלד", "תע\"ל", "תעל"],
        "ideology_tags": ["ערבי-לאומי", "זכויות מיעוטים", "אנטי-כיבוש"],
        "stances": {
            "ביטחון_לאומי": "נגד_חזק",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "חילוני",
            "הרפורמה_המשפטית": "נגד",
            "שני_מדינות": "בעד_חזק",
            "גיוס_חרדים": "ניטרלי",
            "תקציב_ביטחון": "הקטנה",
            "זכויות_מיעוטים": "הרחבה",
        },
        "rhetoric_style": "ideologue",
        "loyalty_base": 0.85,
        "personality_template": "דמות לאומית ערבית עם דגש על זכויות לאומיות וביקורת חריפה על הכיבוש",
    },
    {
        "patterns": ["רע\"ם", "ראם", "רעם", "המאוחדת"],
        "ideology_tags": ["ערבי-אסלאמי", "פרגמטי", "רווחה"],
        "stances": {
            "ביטחון_לאומי": "ניטרלי",
            "כלכלה": "סוציאלי",
            "דת_ומדינה": "דתי",
            "הרפורמה_המשפטית": "ניטרלי",
            "שני_מדינות": "בעד",
            "גיוס_חרדים": "ניטרלי",
            "תקציב_ביטחון": "שימור",
            "זכויות_מיעוטים": "הרחבה",
        },
        "rhetoric_style": "pragmatist",
        "loyalty_base": 0.70,
        "personality_template": "דמות ערבית-אסלאמית פרגמטית, מוכנה לשתף פעולה עם כל ממשלה לטובת הציבור הערבי",
    },
    # --- New Hope / other center-right ---
    {
        "patterns": ["תקווה חדשה", "ימינה"],
        "ideology_tags": ["ימין מתון", "ליברלי", "ביטחוני"],
        "stances": {
            "ביטחון_לאומי": "בעד",
            "כלכלה": "שוק_חופשי",
            "דת_ומדינה": "מסורתי",
            "הרפורמה_המשפטית": "נגד",
            "שני_מדינות": "נגד",
            "גיוס_חרדים": "בעד",
            "תקציב_ביטחון": "הגדלה",
            "זכויות_מיעוטים": "שימור",
        },
        "rhetoric_style": "technocrat",
        "loyalty_base": 0.65,
        "personality_template": "דמות ימנית-מתונה עם גישה ליברלית לנושאים אזרחיים ועמדה ביטחונית תקיפה",
    },
]

# Fallback for unrecognized factions
_DEFAULT_RULE: Dict[str, Any] = {
    "ideology_tags": ["לא מסווג"],
    "stances": {
        "ביטחון_לאומי": "ניטרלי",
        "כלכלה": "מעורב",
        "דת_ומדינה": "מסורתי",
        "הרפורמה_המשפטית": "ניטרלי",
        "שני_מדינות": "ניטרלי",
        "גיוס_חרדים": "ניטרלי",
        "תקציב_ביטחון": "שימור",
        "זכויות_מיעוטים": "שימור",
    },
    "rhetoric_style": "pragmatist",
    "loyalty_base": 0.70,
    "personality_template": "דמות פוליטית ללא מיצוב אידיאולוגי ברור",
}


def _match_faction(faction: str) -> Dict[str, Any]:
    """Return the first matching rule for a faction name, or default."""
    faction_lower = faction.strip()
    for rule in _FACTION_RULES:
        for pat in rule["patterns"]:
            if pat in faction_lower:
                return rule
    return _DEFAULT_RULE


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------

class KnessetPersonaGenerator:
    """Generates KnessetPersona objects from raw MK entity data.

    Supports two generation modes:
    - LLM-based: uses LLMRouter.chat_json with task_type="knesset_persona"
    - Offline: heuristic rules based on faction affiliation (no API calls)

    Parameters
    ----------
    router : LLMRouter | None
        The LLM router instance. Required only for LLM-based generation.
    graph_storage : Any | None
        Optional graph storage for enriching MK data before generation.
    """

    def __init__(self, router=None, graph_storage=None):
        self.router = router
        self.graph_storage = graph_storage

    # ------------------------------------------------------------------
    # Public API — LLM-based (requires explicit approval for API calls)
    # ------------------------------------------------------------------

    def generate_persona(self, mk_data: dict) -> KnessetPersona:
        """Generate a rich persona via LLM call.

        NOTE: This calls the LLM. Do NOT invoke without Mark's explicit
        approval. For cost-free generation use `generate_persona_offline`.

        Parameters
        ----------
        mk_data : dict
            Raw MK entity data with at minimum: name_he, name_en, faction,
            faction_id. Optional: gender, knesset_person_id, positions,
            knesset_nums, influence_score, coalition_member, committee_roles,
            twitter_handle.

        Returns
        -------
        KnessetPersona
        """
        if self.router is None:
            raise RuntimeError(
                "LLMRouter not configured. Use generate_persona_offline() "
                "or pass a router to the constructor."
            )

        prompt = self._build_persona_prompt(mk_data)
        messages = [
            {"role": "system", "content": "אתה מומחה לפוליטיקה ישראלית. ענה בפורמט JSON בלבד."},
            {"role": "user", "content": prompt},
        ]

        try:
            result = self.router.chat_json(
                task_type="knesset_persona",
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
            )
            return self._parse_persona_response(result, mk_data)
        except Exception as e:
            logger.warning(
                "LLM persona generation failed for %s, falling back to offline: %s",
                mk_data.get("name_he", "unknown"), e,
            )
            return self.generate_persona_offline(mk_data)

    def generate_persona_offline(self, mk_data: dict) -> KnessetPersona:
        """Generate a persona using heuristic rules — no LLM call.

        Derives ideology, stances, rhetoric style, and loyalty from faction
        affiliation and basic metadata. Suitable for bulk generation and
        testing without API costs.

        Parameters
        ----------
        mk_data : dict
            Same schema as `generate_persona`.

        Returns
        -------
        KnessetPersona
        """
        faction = mk_data.get("faction", "")
        rule = _match_faction(faction)

        # Build agent_id from knesset_person_id or name
        person_id = mk_data.get("knesset_person_id", 0)
        name_en = mk_data.get("name_en", "unknown").lower().replace(" ", "_")
        agent_id = f"mk_{person_id}" if person_id else f"mk_{name_en}"

        # Adjust loyalty based on coalition membership
        is_coalition = mk_data.get("coalition_member", False)
        loyalty = rule["loyalty_base"]
        if is_coalition:
            loyalty = min(1.0, loyalty + 0.05)

        # Build personality string
        name_he = mk_data.get("name_he", "")
        gender_word = "חברת" if mk_data.get("gender", "male") == "female" else "חבר"
        positions = mk_data.get("positions", [])
        positions_str = ", ".join(positions[:3]) if positions else "חבר/ת כנסת"

        personality = (
            f"{name_he} — {gender_word} כנסת מסיעת {faction}. "
            f"{rule['personality_template']}. "
            f"תפקידים: {positions_str}."
        )

        return KnessetPersona(
            agent_id=agent_id,
            name_he=name_he,
            name_en=mk_data.get("name_en", ""),
            faction=faction,
            faction_id=mk_data.get("faction_id", ""),
            knesset_person_id=person_id,
            gender=mk_data.get("gender", "male"),
            is_current_mk=mk_data.get("is_current_mk", True),
            coalition_member=is_coalition,
            influence_score=mk_data.get("influence_score", 50),
            loyalty_score=round(loyalty, 2),
            ideology_tags=list(rule["ideology_tags"]),
            stances=dict(rule["stances"]),
            personality=personality,
            rhetoric_style=rule["rhetoric_style"],
            committee_roles=mk_data.get("committee_roles", []),
            voting_history_summary=mk_data.get("voting_history_summary", ""),
            twitter_handle=mk_data.get("twitter_handle"),
        )

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def generate_all_personas(
        self,
        mk_entities: List[dict],
        cache_dir: Optional[str] = None,
        use_llm: bool = False,
    ) -> List[KnessetPersona]:
        """Generate personas for a list of MK entities.

        Parameters
        ----------
        mk_entities : list[dict]
            List of raw MK data dicts.
        cache_dir : str | None
            If provided, check for existing persona JSON and skip generation
            if found. Newly generated personas are saved to
            ``{cache_dir}/{agent_id}.json``.
        use_llm : bool
            If True, use LLM-based generation (requires router + approval).
            Defaults to False (offline heuristic mode).

        Returns
        -------
        list[KnessetPersona]
        """
        if cache_dir:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)

        personas: List[KnessetPersona] = []
        total = len(mk_entities)

        for idx, raw_mk in enumerate(mk_entities, 1):
            # Flatten: entities from orchestrator have nested "properties"
            props = raw_mk.get("properties", {})
            mk_data = {
                "name_he": raw_mk.get("name_he", raw_mk.get("name", "")),
                "name_en": props.get("name_en", raw_mk.get("name_en", "")),
                "knesset_person_id": props.get("knesset_person_id", raw_mk.get("knesset_person_id", 0)),
                "faction": props.get("party", raw_mk.get("faction", "")),
                "gender": props.get("gender", raw_mk.get("gender", "")),
                "is_current_mk": props.get("is_current_mk", raw_mk.get("is_current_mk", False)),
                "positions": props.get("positions", raw_mk.get("positions", [])),
                "influence_score": raw_mk.get("influence_score", 40),
                "subtype": props.get("subtype", raw_mk.get("subtype", "politician")),
            }
            person_id = mk_data.get("knesset_person_id", 0)
            name_en = mk_data.get("name_en", "unknown").lower().replace(" ", "_")
            mk_id = f"mk_{person_id}" if person_id else f"mk_{name_en}"

            # Check cache
            if cache_dir:
                cache_path = Path(cache_dir) / f"{mk_id}.json"
                if cache_path.exists():
                    try:
                        data = json.loads(cache_path.read_text(encoding="utf-8"))
                        persona = KnessetPersona.from_dict(data)
                        personas.append(persona)
                        logger.info("[%d/%d] Loaded cached: %s", idx, total, mk_id)
                        continue
                    except Exception as e:
                        logger.warning("Cache load failed for %s: %s", mk_id, e)

            # Generate
            if use_llm:
                persona = self.generate_persona(mk_data)
            else:
                persona = self.generate_persona_offline(mk_data)

            personas.append(persona)

            # Save to cache
            if cache_dir:
                cache_path = Path(cache_dir) / f"{mk_id}.json"
                try:
                    cache_path.write_text(
                        json.dumps(persona.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as e:
                    logger.warning("Cache save failed for %s: %s", mk_id, e)

            logger.info("[%d/%d] Generated: %s (%s)", idx, total, mk_id, persona.faction)

        logger.info("Persona generation complete: %d/%d", len(personas), total)
        return personas

    def load_cached_personas(self, cache_dir: str) -> List[KnessetPersona]:
        """Load all persona JSONs from a cache directory.

        Parameters
        ----------
        cache_dir : str
            Directory containing ``{mk_id}.json`` files.

        Returns
        -------
        list[KnessetPersona]
        """
        personas: List[KnessetPersona] = []
        cache_path = Path(cache_dir)

        if not cache_path.exists():
            logger.warning("Cache directory does not exist: %s", cache_dir)
            return personas

        for json_file in sorted(cache_path.glob("mk_*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                persona = KnessetPersona.from_dict(data)
                personas.append(persona)
            except Exception as e:
                logger.warning("Failed to load %s: %s", json_file.name, e)

        logger.info("Loaded %d personas from cache: %s", len(personas), cache_dir)
        return personas

    # ------------------------------------------------------------------
    # Auxiliary persona generation (non-MK participants)
    # ------------------------------------------------------------------

    def generate_auxiliary_personas(self, count: int = 10) -> List[AuxiliaryPersona]:
        """Generate a set of common auxiliary participants.

        Creates a mix of advisors, journalists, lobbyists with
        Hebrew names and appropriate personality traits.
        No LLM call needed — hardcoded list with role-based stances.

        Parameters
        ----------
        count : int
            Max personas to return (up to 10).

        Returns
        -------
        list[AuxiliaryPersona]
        """
        import random

        _AUXILIARY_ROSTER: List[Dict[str, Any]] = [
            # --- Journalists (3) ---
            {
                "agent_id": "aux_journalist_01",
                "name_he": "אמנון אברמוביץ'",
                "name_en": "Amnon Abramovich",
                "role": "journalist",
                "affiliation": "ערוץ חדשות",
                "influence_score": 65,
                "personality": "עיתונאי חוקר ותיק, ידוע בראיונות תוקפניים ובביקורת חריפה על השלטון. לא חושש מעימותים.",
                "expertise_areas": ["פוליטיקה", "ביטחון", "שחיתות"],
                "stances_pool": {
                    "הרפורמה_המשפטית": ["נגד", "נגד_חזק"],
                    "שקיפות_שלטונית": ["בעד_חזק"],
                    "חופש_העיתונות": ["בעד_חזק"],
                },
            },
            {
                "agent_id": "aux_journalist_02",
                "name_he": "בן כספית",
                "name_en": "Ben Caspit",
                "role": "journalist",
                "affiliation": "מעריב",
                "influence_score": 60,
                "personality": "פרשן פוליטי בכיר עם קשרים עמוקים בממסד הביטחוני. כותב טורים ביקורתיים אך מאוזנים.",
                "expertise_areas": ["פוליטיקה", "ביטחון", "דיפלומטיה"],
                "stances_pool": {
                    "הרפורמה_המשפטית": ["נגד", "ניטרלי"],
                    "שקיפות_שלטונית": ["בעד"],
                    "חופש_העיתונות": ["בעד_חזק"],
                },
            },
            {
                "agent_id": "aux_journalist_03",
                "name_he": "רינה מצליח",
                "name_en": "Rina Matzliach",
                "role": "journalist",
                "affiliation": "חדשות 12",
                "influence_score": 55,
                "personality": "כתבת פוליטית חדה וישירה. מתמחה בחשיפת עסקאות פוליטיות ובלחצים קואליציוניים.",
                "expertise_areas": ["פוליטיקה פנימית", "קואליציה", "תקשורת"],
                "stances_pool": {
                    "הרפורמה_המשפטית": ["נגד", "ניטרלי"],
                    "שקיפות_שלטונית": ["בעד_חזק"],
                    "חופש_העיתונות": ["בעד_חזק"],
                },
            },
            # --- Lobbyists (2) ---
            {
                "agent_id": "aux_lobbyist_01",
                "name_he": "דוד גרנות",
                "name_en": "David Granot",
                "role": "lobbyist",
                "affiliation": "התאחדות התעשיינים",
                "influence_score": 50,
                "personality": "לוביסט כלכלי ותיק, מייצג את האינטרסים של המגזר העסקי. פרגמטי ומחובר לכל הסיעות.",
                "expertise_areas": ["כלכלה", "תעשייה", "רגולציה"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה"],
                    "תקציב_ביטחון": ["שימור", "הגדלה"],
                },
            },
            {
                "agent_id": "aux_lobbyist_02",
                "name_he": "נועה לנדבר",
                "name_en": "Noa Landver",
                "role": "lobbyist",
                "affiliation": "פורום החברה האזרחית",
                "influence_score": 45,
                "personality": "לוביסטית חברתית הפועלת למען זכויות אדם וצדק חברתי. משפיעה דרך ארגוני מגזר שלישי.",
                "expertise_areas": ["זכויות אדם", "רווחה", "חינוך"],
                "stances_pool": {
                    "זכויות_מיעוטים": ["הרחבה"],
                    "כלכלה": ["סוציאלי"],
                    "הרפורמה_המשפטית": ["נגד", "נגד_חזק"],
                },
            },
            # --- Political Advisors (2) ---
            {
                "agent_id": "aux_advisor_01",
                "name_he": "ראובן אדלר",
                "name_en": "Reuven Adler",
                "role": "advisor",
                "affiliation": "קואליציה",
                "influence_score": 55,
                "personality": "יועץ אסטרטגי ותיק, מומחה לקמפיינים ולמיתוג פוליטי. עובד בעיקר עם מפלגות ימין.",
                "expertise_areas": ["אסטרטגיה", "תקשורת", "קמפיינים"],
                "stances_pool": {
                    "הרפורמה_המשפטית": ["בעד", "ניטרלי"],
                    "ביטחון_לאומי": ["בעד", "בעד_חזק"],
                    "כלכלה": ["שוק_חופשי", "מעורב"],
                },
            },
            {
                "agent_id": "aux_advisor_02",
                "name_he": "לילך שילה",
                "name_en": "Lilach Shila",
                "role": "advisor",
                "affiliation": "אופוזיציה",
                "influence_score": 50,
                "personality": "יועצת פוליטית עם רקע אקדמי, מתמחה בניתוח דעת קהל ובמגמות חברתיות. עובדת עם מפלגות מרכז-שמאל.",
                "expertise_areas": ["דעת קהל", "מדיניות חברתית", "אסטרטגיה"],
                "stances_pool": {
                    "הרפורמה_המשפטית": ["נגד"],
                    "כלכלה": ["מעורב", "סוציאלי"],
                    "זכויות_מיעוטים": ["הרחבה", "שימור"],
                },
            },
            # --- Legal Advisor (1) ---
            {
                "agent_id": "aux_legal_01",
                "name_he": "פרופ' יוסף גביזון",
                "name_en": "Prof. Yosef Gavison",
                "role": "legal_advisor",
                "affiliation": "אקדמיה",
                "influence_score": 60,
                "personality": "משפטן חוקתי בכיר, מומחה למשפט ציבורי ולזכויות אדם. קולו נשמע בדיוני חקיקה מרכזיים.",
                "expertise_areas": ["משפט חוקתי", "זכויות אדם", "חקיקה"],
                "stances_pool": {
                    "הרפורמה_המשפטית": ["נגד", "נגד_חזק"],
                    "שקיפות_שלטונית": ["בעד_חזק"],
                    "זכויות_מיעוטים": ["הרחבה"],
                },
            },
            # --- Economist (1) ---
            {
                "agent_id": "aux_economist_01",
                "name_he": "ד\"ר מיכל שרון",
                "name_en": "Dr. Michal Sharon",
                "role": "economist",
                "affiliation": "מכון שורש",
                "influence_score": 45,
                "personality": "כלכלנית מחקרית עם השפעה על מדיניות תקציבית. מציגה ניתוחים מבוססי נתונים בוועדות הכנסת.",
                "expertise_areas": ["מקרו-כלכלה", "תקציב", "אי-שוויון"],
                "stances_pool": {
                    "כלכלה": ["מעורב", "סוציאלי"],
                    "תקציב_ביטחון": ["שימור", "הקטנה"],
                    "רווחה": ["הרחבה"],
                },
            },
            # --- Military Analyst (1) ---
            {
                "agent_id": "aux_military_01",
                "name_he": "אלוף (מיל') עמוס גלעד",
                "name_en": "Maj. Gen. (res.) Amos Gilad",
                "role": "advisor",
                "affiliation": "מערכת הביטחון",
                "influence_score": 55,
                "personality": "אנליסט ביטחוני בכיר לשעבר, מומחה לאיומים אסטרטגיים ולמזרח התיכון. דעותיו נשמעות בשיח הציבורי.",
                "expertise_areas": ["ביטחון לאומי", "מודיעין", "גיאופוליטיקה"],
                "stances_pool": {
                    "ביטחון_לאומי": ["בעד_חזק"],
                    "תקציב_ביטחון": ["הגדלה"],
                    "שני_מדינות": ["ניטרלי", "נגד"],
                },
            },
        ]

        personas: List[AuxiliaryPersona] = []
        for entry in _AUXILIARY_ROSTER[:count]:
            # Randomize stances from the pool for each persona
            stances: Dict[str, str] = {}
            for stance_key, options in entry["stances_pool"].items():
                stances[stance_key] = random.choice(options)

            persona = AuxiliaryPersona(
                agent_id=entry["agent_id"],
                name_he=entry["name_he"],
                name_en=entry["name_en"],
                role=entry["role"],
                affiliation=entry["affiliation"],
                influence_score=entry["influence_score"],
                personality=entry["personality"],
                expertise_areas=entry["expertise_areas"],
                stances=stances,
                can_vote=False,
                can_propose_bill=False,
                can_lobby=entry["role"] in ("lobbyist", "advisor"),
                can_speak=True,
            )
            personas.append(persona)

        logger.info("Generated %d auxiliary personas", len(personas))
        return personas

    def generate_tycoon_personas(self) -> List[AuxiliaryPersona]:
        """Generate Israeli tycoon/industrialist agents."""
        import random

        _TYCOON_ROSTER: List[Dict[str, Any]] = [
            {
                "agent_id": "tycoon_01",
                "name_he": "נוחי דנקנר",
                "name_en": "Nochi Dankner",
                "affiliation": "נדל\"ן, תעשייה",
                "influence_score": 70,
                "personality": "בעל IDB לשעבר, מכיר כל פוליטיקאי.",
                "expertise_areas": ["נדל\"ן", "תעשייה", "פיננסים"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה", "ניטרלי"],
                    "תקציב_ביטחון": ["שימור"],
                    "זכויות_עובדים": ["צמצום", "שימור"],
                },
            },
            {
                "agent_id": "tycoon_02",
                "name_he": "שרי אריסון",
                "name_en": "Shari Arison",
                "affiliation": "בנקאות, צדקה",
                "influence_score": 75,
                "personality": "בעלת בנק הפועלים, פעילה חברתית.",
                "expertise_areas": ["בנקאות", "פילנתרופיה", "חברה"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי", "מעורב"],
                    "רגולציה": ["שימור", "ניטרלי"],
                    "רווחה": ["הרחבה", "שימור"],
                    "סביבה": ["בעד", "בעד_חזק"],
                },
            },
            {
                "agent_id": "tycoon_03",
                "name_he": "מוטי בן משה",
                "name_en": "Moti Ben Moshe",
                "affiliation": "תקשורת, נדל\"ן",
                "influence_score": 60,
                "personality": "בעל ערוץ הספורט וקבוצות מדיה.",
                "expertise_areas": ["תקשורת", "נדל\"ן", "ספורט"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה"],
                    "חופש_העיתונות": ["בעד", "ניטרלי"],
                    "תקציב_ביטחון": ["שימור"],
                },
            },
            {
                "agent_id": "tycoon_04",
                "name_he": "אלפרד אקירוב",
                "name_en": "Alfred Akirov",
                "affiliation": "נדל\"ן, תיירות",
                "influence_score": 65,
                "personality": "מלונות דן, בנייה בת\"א.",
                "expertise_areas": ["נדל\"ן", "תיירות", "מלונאות"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה", "שימור"],
                    "תיירות": ["הרחבה"],
                    "תשתיות": ["בעד_חזק", "בעד"],
                },
            },
            {
                "agent_id": "tycoon_05",
                "name_he": "צדיק בינו",
                "name_en": "Tsadik Bino",
                "affiliation": "אנרגיה",
                "influence_score": 60,
                "personality": "דלק אנרגיה, גז טבעי.",
                "expertise_areas": ["אנרגיה", "גז טבעי", "תשתיות"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה"],
                    "סביבה": ["ניטרלי", "נגד"],
                    "אנרגיה": ["מסורתי", "מעורב"],
                },
            },
            {
                "agent_id": "tycoon_06",
                "name_he": "יצחק תשובה",
                "name_en": "Yitzhak Tshuva",
                "affiliation": "אנרגיה, נדל\"ן",
                "influence_score": 70,
                "personality": "דלק, The Phoenix, נדל\"ן ביום.",
                "expertise_areas": ["אנרגיה", "נדל\"ן", "ביטוח"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה", "ניטרלי"],
                    "תקציב_ביטחון": ["שימור", "הגדלה"],
                    "אנרגיה": ["מסורתי"],
                },
            },
            {
                "agent_id": "tycoon_07",
                "name_he": "ארנון מילצ'ן",
                "name_en": "Arnon Milchan",
                "affiliation": "תקשורת, הייטק",
                "influence_score": 65,
                "personality": "מפיק הוליוודי, קשרים פוליטיים.",
                "expertise_areas": ["תקשורת", "בידור", "הייטק"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "ביטחון_לאומי": ["בעד_חזק", "בעד"],
                    "דיפלומטיה": ["פרו-אמריקאי"],
                    "חופש_העיתונות": ["ניטרלי"],
                },
            },
            {
                "agent_id": "tycoon_08",
                "name_he": "עידן עופר",
                "name_en": "Idan Ofer",
                "affiliation": "ספנות, כימיקלים",
                "influence_score": 70,
                "personality": "צים, כיל, פעילות בינלאומית.",
                "expertise_areas": ["ספנות", "כימיקלים", "סחר בינלאומי"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "רגולציה": ["הפחתה"],
                    "סביבה": ["ניטרלי", "נגד"],
                    "סחר_חוץ": ["הרחבה"],
                },
            },
            {
                "agent_id": "tycoon_09",
                "name_he": "אלי אזור",
                "name_en": "Eli Azur",
                "affiliation": "הייטק, ביומד",
                "influence_score": 55,
                "personality": "אינסייטק, מדיגוס, חדשנות.",
                "expertise_areas": ["הייטק", "ביומד", "חדשנות"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי", "מעורב"],
                    "רגולציה": ["הפחתה"],
                    "חינוך": ["הרחבה"],
                    "מחקר_ופיתוח": ["בעד_חזק"],
                },
            },
            {
                "agent_id": "tycoon_10",
                "name_he": "מרים אדלסון",
                "name_en": "Miriam Adelson",
                "affiliation": "תקשורת",
                "influence_score": 75,
                "personality": "ישראל היום, השפעה תקשורתית.",
                "expertise_areas": ["תקשורת", "פוליטיקה", "פילנתרופיה"],
                "stances_pool": {
                    "כלכלה": ["שוק_חופשי"],
                    "ביטחון_לאומי": ["בעד_חזק"],
                    "הרפורמה_המשפטית": ["בעד", "ניטרלי"],
                    "חופש_העיתונות": ["ניטרלי", "נגד"],
                },
            },
        ]

        personas: List[AuxiliaryPersona] = []
        for entry in _TYCOON_ROSTER:
            stances: Dict[str, str] = {}
            for stance_key, options in entry["stances_pool"].items():
                stances[stance_key] = random.choice(options)

            persona = AuxiliaryPersona(
                agent_id=entry["agent_id"],
                name_he=entry["name_he"],
                name_en=entry["name_en"],
                role="tycoon",
                affiliation=entry["affiliation"],
                influence_score=entry["influence_score"],
                personality=entry["personality"],
                expertise_areas=entry["expertise_areas"],
                stances=stances,
                can_vote=False,
                can_propose_bill=False,
                can_lobby=True,
                can_speak=True,
            )
            personas.append(persona)

        logger.info("Generated %d tycoon personas", len(personas))
        return personas

    def generate_activist_personas(self) -> List[AuxiliaryPersona]:
        """Generate social activist agents."""
        import random

        _ACTIVIST_ROSTER: List[Dict[str, Any]] = [
            {
                "agent_id": "activist_01",
                "name_he": "נציג תנועת המחאה",
                "name_en": "Protest Movement Representative",
                "affiliation": "תנועת מחאה חברתית",
                "influence_score": 45,
                "personality": "מוביל מחאה חברתית, דיור ויוקר מחיה.",
                "expertise_areas": ["מחאה חברתית", "דיור", "יוקר מחיה"],
                "stances_pool": {
                    "כלכלה": ["סוציאלי"],
                    "רווחה": ["הרחבה"],
                    "דיור": ["בעד_חזק"],
                    "רגולציה": ["הגברה", "שימור"],
                },
            },
            {
                "agent_id": "activist_02",
                "name_he": "נציגת ארגון זכויות אדם",
                "name_en": "Human Rights Organization Representative",
                "affiliation": "ארגון זכויות אדם",
                "influence_score": 40,
                "personality": "מנהלת ארגון זכויות, שוויון ומיעוטים.",
                "expertise_areas": ["זכויות אדם", "שוויון", "מיעוטים"],
                "stances_pool": {
                    "זכויות_מיעוטים": ["הרחבה"],
                    "הרפורמה_המשפטית": ["נגד", "נגד_חזק"],
                    "שקיפות_שלטונית": ["בעד_חזק"],
                    "דמוקרטיה": ["בעד_חזק"],
                },
            },
            {
                "agent_id": "activist_03",
                "name_he": "ראש מועצה אזורית (דרום)",
                "name_en": "Regional Council Head (South)",
                "affiliation": "מועצה אזורית בנגב",
                "influence_score": 50,
                "personality": "ראש מועצה בנגב, פריפריה.",
                "expertise_areas": ["פריפריה", "תשתיות", "חינוך"],
                "stances_pool": {
                    "תקציב_ביטחון": ["הגדלה", "שימור"],
                    "פריפריה": ["בעד_חזק"],
                    "תשתיות": ["בעד_חזק"],
                    "חינוך": ["הרחבה"],
                },
            },
            {
                "agent_id": "activist_04",
                "name_he": "נציג ועד עובדים",
                "name_en": "Workers Committee Representative",
                "affiliation": "ועד עובדים ארצי",
                "influence_score": 45,
                "personality": "יו\"ר ועד עובדים ארצי, זכויות עובדים.",
                "expertise_areas": ["זכויות עובדים", "שכר", "תעסוקה"],
                "stances_pool": {
                    "כלכלה": ["סוציאלי"],
                    "זכויות_עובדים": ["הרחבה"],
                    "רגולציה": ["הגברה"],
                    "רווחה": ["הרחבה"],
                },
            },
            {
                "agent_id": "activist_05",
                "name_he": "פעילת סביבה",
                "name_en": "Environmental Activist",
                "affiliation": "ארגון סביבתי",
                "influence_score": 35,
                "personality": "מובילת מאבק אקלים, אנרגיה ירוקה.",
                "expertise_areas": ["סביבה", "אקלים", "אנרגיה ירוקה"],
                "stances_pool": {
                    "סביבה": ["בעד_חזק"],
                    "אנרגיה": ["ירוק", "מעורב"],
                    "רגולציה": ["הגברה"],
                    "כלכלה": ["סוציאלי", "מעורב"],
                },
            },
            {
                "agent_id": "activist_06",
                "name_he": "נציג ארגון מתנחלים",
                "name_en": "Settler Organization Representative",
                "affiliation": "מועצת יש\"ע",
                "influence_score": 55,
                "personality": "דובר מועצת יש\"ע, התיישבות.",
                "expertise_areas": ["התיישבות", "ביטחון", "קרקעות"],
                "stances_pool": {
                    "שני_מדינות": ["נגד_חזק"],
                    "ביטחון_לאומי": ["בעד_חזק"],
                    "תקציב_ביטחון": ["הגדלה"],
                    "התיישבות": ["בעד_חזק"],
                },
            },
        ]

        personas: List[AuxiliaryPersona] = []
        for entry in _ACTIVIST_ROSTER:
            stances: Dict[str, str] = {}
            for stance_key, options in entry["stances_pool"].items():
                stances[stance_key] = random.choice(options)

            persona = AuxiliaryPersona(
                agent_id=entry["agent_id"],
                name_he=entry["name_he"],
                name_en=entry["name_en"],
                role="activist",
                affiliation=entry["affiliation"],
                influence_score=entry["influence_score"],
                personality=entry["personality"],
                expertise_areas=entry["expertise_areas"],
                stances=stances,
                can_vote=False,
                can_propose_bill=False,
                can_lobby=True,
                can_speak=True,
            )
            personas.append(persona)

        logger.info("Generated %d activist personas", len(personas))
        return personas

    # ------------------------------------------------------------------
    # LLM prompt construction
    # ------------------------------------------------------------------

    def _build_persona_prompt(self, mk_data: dict) -> str:
        """Build a Hebrew prompt asking the LLM to generate a rich persona."""
        name_he = mk_data.get("name_he", "לא ידוע")
        faction = mk_data.get("faction", "לא ידוע")
        gender = mk_data.get("gender", "male")
        gender_he = "נקבה" if gender == "female" else "זכר"

        positions = mk_data.get("positions", [])
        positions_formatted = ", ".join(positions) if positions else "חבר/ת כנסת"

        knesset_nums = mk_data.get("knesset_nums", [])
        knesset_str = ", ".join(str(k) for k in knesset_nums) if knesset_nums else "הכנסת הנוכחית"

        influence = mk_data.get("influence_score", 50)

        return f"""בהתבסס על המידע הבא על חבר/ת הכנסת:

שם: {name_he}
סיעה: {faction}
מגדר: {gender_he}
תפקידים: {positions_formatted}
כנסות: {knesset_str}
ציון השפעה: {influence}/95

צור פרופיל אישיות מפורט בפורמט JSON:
{{
  "ideology_tags": ["תג1", "תג2", "תג3"],
  "personality": "תיאור אישיות בעברית — סגנון דיבור, גישה למו\\"מ, נאמנות",
  "stances": {{
    "ביטחון_לאומי": "בעד_חזק/בעד/ניטרלי/נגד/נגד_חזק",
    "כלכלה": "שוק_חופשי/מעורב/סוציאלי",
    "דת_ומדינה": "חילוני/מסורתי/דתי/חרדי",
    "הרפורמה_המשפטית": "בעד/נגד/ניטרלי",
    "שני_מדינות": "בעד/נגד/ניטרלי",
    "גיוס_חרדים": "בעד/נגד/ניטרלי",
    "תקציב_ביטחון": "הגדלה/שימור/הקטנה",
    "זכויות_מיעוטים": "הרחבה/שימור/צמצום"
  }},
  "rhetoric_style": "populist/technocrat/ideologue/pragmatist",
  "loyalty_score": 0.0-1.0
}}

החזר JSON בלבד, ללא טקסט נוסף."""

    # ------------------------------------------------------------------
    # LLM response parsing
    # ------------------------------------------------------------------

    def _parse_persona_response(
        self, response: Any, mk_data: dict
    ) -> KnessetPersona:
        """Parse LLM JSON response and merge with factual mk_data.

        Parameters
        ----------
        response : dict | str
            The LLM response — either a parsed dict (from chat_json) or
            a raw JSON string.
        mk_data : dict
            Original MK entity data for factual fields.

        Returns
        -------
        KnessetPersona
        """
        # Parse if string
        if isinstance(response, str):
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
            if json_match:
                response = json_match.group(1).strip()
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM response as JSON, using offline fallback")
                return self.generate_persona_offline(mk_data)

        if not isinstance(response, dict):
            logger.warning("LLM response is not a dict, using offline fallback")
            return self.generate_persona_offline(mk_data)

        # Build agent_id
        person_id = mk_data.get("knesset_person_id", 0)
        name_en = mk_data.get("name_en", "unknown").lower().replace(" ", "_")
        agent_id = f"mk_{person_id}" if person_id else f"mk_{name_en}"

        # Extract LLM-generated fields with safe defaults
        ideology_tags = response.get("ideology_tags", [])
        personality = response.get("personality", "")
        stances = response.get("stances", {})
        rhetoric_style = response.get("rhetoric_style", "technocrat")
        loyalty_score = response.get("loyalty_score", 0.8)

        # Validate rhetoric_style
        valid_styles = {"populist", "technocrat", "ideologue", "pragmatist"}
        if rhetoric_style not in valid_styles:
            rhetoric_style = "technocrat"

        # Validate loyalty_score
        try:
            loyalty_score = float(loyalty_score)
            loyalty_score = max(0.0, min(1.0, loyalty_score))
        except (ValueError, TypeError):
            loyalty_score = 0.8

        return KnessetPersona(
            agent_id=agent_id,
            name_he=mk_data.get("name_he", ""),
            name_en=mk_data.get("name_en", ""),
            faction=mk_data.get("faction", ""),
            faction_id=mk_data.get("faction_id", ""),
            knesset_person_id=person_id,
            gender=mk_data.get("gender", "male"),
            is_current_mk=mk_data.get("is_current_mk", True),
            coalition_member=mk_data.get("coalition_member", False),
            influence_score=mk_data.get("influence_score", 50),
            loyalty_score=round(loyalty_score, 2),
            ideology_tags=ideology_tags,
            stances=stances,
            personality=personality,
            rhetoric_style=rhetoric_style,
            committee_roles=mk_data.get("committee_roles", []),
            voting_history_summary=mk_data.get("voting_history_summary", ""),
            twitter_handle=mk_data.get("twitter_handle"),
        )
