"""Knesset Member (MK) collector via OData API.

Fetches person data, positions, and faction memberships from the
Knesset OData endpoint and builds MK + Faction nodes with MEMBER_OF edges.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.members")

# Factions associated with the Religious Zionism movement
RELIGIOUS_ZIONISM_FACTIONS: Set[str] = {
    "הציונות הדתית",
    "עוצמה יהודית",
    "הבית היהודי",
    "ימינה",
    "איחוד הלאומי",
    "נועם",
    "תקומה",
}

# Knesset numbers to cover (20th–25th)
KNESSET_RANGE = range(20, 26)


class KnessetMemberCollector(BaseKnessetCollector):
    """Collects MK data from the Knesset OData API.

    Entities used:
        KNS_Person          — biographical data for all persons
        KNS_PersonToPosition — role / faction assignments per Knesset
        KNS_Faction          — faction (party) metadata
    """

    SOURCE_ID = "knesset:odata:members"

    def get_source_id(self) -> str:
        return self.SOURCE_ID

    # ------------------------------------------------------------------
    # Main collection entry point
    # ------------------------------------------------------------------

    def collect_incremental(
        self,
        cursor_state: Optional[Dict[str, Any]] = None,
    ) -> CollectionResult:
        start = time.time()
        cursor_state = cursor_state or {}
        last_person_id = cursor_state.get("last_person_id", 0)

        try:
            # 1. Fetch persons -----------------------------------------
            persons = self._fetch_persons(last_person_id)
            if not persons:
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    new_cursor=cursor_state,
                    duration_seconds=time.time() - start,
                )

            person_ids = [p.get("PersonID", 0) for p in persons]
            max_person_id = max(person_ids) if person_ids else last_person_id

            # 2. Fetch all factions ------------------------------------
            factions = self._fetch_factions()
            faction_map = self._build_faction_map(factions)

            # 3. Fetch positions for the fetched persons ---------------
            positions = self._fetch_positions_for_persons(person_ids)
            positions_by_person = self._group_positions_by_person(positions)

            # 4. Build and upsert nodes / edges ------------------------
            new_count = 0
            updated_count = 0

            # Faction nodes
            for faction in factions:
                self._upsert_faction_node(faction)

            # MK nodes + MEMBER_OF edges
            for person in persons:
                pid = person.get("PersonID", 0)
                person_positions = positions_by_person.get(pid, [])
                was_new = self._upsert_mk_node(
                    person, person_positions, faction_map,
                )
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Create MEMBER_OF edges for each faction assignment
                self._create_membership_edges(pid, person_positions)

            new_cursor = {"last_person_id": max_person_id}

            logger.info(
                "%s: collected %d persons (%d new, %d updated), %d factions",
                self.get_source_id(),
                len(persons),
                new_count,
                updated_count,
                len(factions),
            )

            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=new_count,
                items_updated=updated_count,
                new_cursor=new_cursor,
                duration_seconds=time.time() - start,
            )

        except Exception as exc:
            logger.exception("%s: collection failed", self.get_source_id())
            return CollectionResult(
                source_id=self.get_source_id(),
                error=str(exc),
                new_cursor=cursor_state,
                duration_seconds=time.time() - start,
            )

    # ------------------------------------------------------------------
    # OData fetch helpers
    # ------------------------------------------------------------------

    def _fetch_persons(self, last_person_id: int) -> List[Dict[str, Any]]:
        """Fetch persons who are current MKs or served in Knessets 20-25.

        Uses incremental cursor: only persons with PersonID > last_person_id.
        """
        # Current MKs
        current_filter = f"IsCurrent eq true and PersonID gt {last_person_id}"
        current_persons = self.fetch_odata_all(
            "KNS_Person",
            params={"$filter": current_filter},
        )

        # Historical MKs from recent Knessets — we get their IDs via positions
        # then fetch person records for any we haven't seen yet
        seen_ids = {p.get("PersonID") for p in current_persons}

        historical_persons: List[Dict[str, Any]] = []
        for knum in KNESSET_RANGE:
            pos_filter = f"KnessetNum eq {knum}"
            positions = self.fetch_odata_all(
                "KNS_PersonToPosition",
                params={"$filter": pos_filter, "$select": "PersonID"},
                page_size=500,
            )
            for pos in positions:
                pid = pos.get("PersonID", 0)
                if pid > last_person_id and pid not in seen_ids:
                    seen_ids.add(pid)
                    person_data = self.fetch_odata(
                        "KNS_Person",
                        params={"$filter": f"PersonID eq {pid}"},
                    )
                    if person_data:
                        historical_persons.extend(person_data)

        all_persons = current_persons + historical_persons
        logger.info(
            "%s: fetched %d persons (%d current, %d historical)",
            self.get_source_id(),
            len(all_persons),
            len(current_persons),
            len(historical_persons),
        )
        return all_persons

    def _fetch_factions(self) -> List[Dict[str, Any]]:
        """Fetch all factions from Knessets 20-25."""
        all_factions: List[Dict[str, Any]] = []
        seen_ids: Set[int] = set()
        for knum in KNESSET_RANGE:
            factions = self.fetch_odata_all(
                "KNS_Faction",
                params={"$filter": f"KnessetNum eq {knum}"},
            )
            for f in factions:
                fid = f.get("FactionID", 0)
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    all_factions.append(f)
        logger.info("%s: fetched %d unique factions", self.get_source_id(), len(all_factions))
        return all_factions

    def _fetch_positions_for_persons(
        self, person_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """Fetch all KNS_PersonToPosition rows for a set of person IDs."""
        all_positions: List[Dict[str, Any]] = []
        # Batch in chunks to avoid overly long $filter expressions
        batch_size = 50
        for i in range(0, len(person_ids), batch_size):
            batch = person_ids[i : i + batch_size]
            filter_parts = " or ".join(f"PersonID eq {pid}" for pid in batch)
            positions = self.fetch_odata_all(
                "KNS_PersonToPosition",
                params={"$filter": filter_parts},
                page_size=500,
            )
            all_positions.extend(positions)
        return all_positions

    # ------------------------------------------------------------------
    # Data transformation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_faction_map(factions: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        """Build FactionID → faction record mapping."""
        return {f.get("FactionID", 0): f for f in factions}

    @staticmethod
    def _group_positions_by_person(
        positions: List[Dict[str, Any]],
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Group position records by PersonID."""
        grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for pos in positions:
            grouped[pos.get("PersonID", 0)].append(pos)
        return dict(grouped)

    # ------------------------------------------------------------------
    # Node / edge upsert
    # ------------------------------------------------------------------

    def _upsert_mk_node(
        self,
        person: Dict[str, Any],
        positions: List[Dict[str, Any]],
        faction_map: Dict[int, Dict[str, Any]],
    ) -> bool:
        """Build and upsert an MK node. Returns True if the node was new."""
        pid = person.get("PersonID", 0)
        node_id = f"mk_{pid}"
        first_name = person.get("FirstName", "")
        last_name = person.get("LastName", "")
        full_name = f"{first_name} {last_name}".strip()

        # Derive faction from most recent position with a FactionID
        faction_name = ""
        faction_id = None
        knesset_numbers: List[int] = []
        position_list: List[Dict[str, Any]] = []
        ideology_tags: List[str] = []

        for pos in sorted(
            positions,
            key=lambda p: p.get("KnessetNum", 0),
            reverse=True,
        ):
            knum = pos.get("KnessetNum", 0)
            if knum and knum not in knesset_numbers:
                knesset_numbers.append(knum)

            fid = pos.get("FactionID")
            if fid and not faction_name:
                faction_rec = faction_map.get(fid, {})
                faction_name = faction_rec.get("Name", "")
                faction_id = fid

            start_date = self.parse_odata_date(pos.get("StartDate"))
            finish_date = self.parse_odata_date(pos.get("FinishDate"))
            position_list.append({
                "position_id": pos.get("PositionID"),
                "knesset_num": knum,
                "faction_id": fid,
                "duty_desc": pos.get("DutyDesc", ""),
                "start_date": start_date,
                "finish_date": finish_date,
            })

        # Tag Religious Zionism affiliation
        for pos in positions:
            fid = pos.get("FactionID")
            if fid:
                fname = faction_map.get(fid, {}).get("Name", "")
                if fname in RELIGIOUS_ZIONISM_FACTIONS:
                    if "religious_zionism" not in ideology_tags:
                        ideology_tags.append("religious_zionism")
                    break

        gender_id = person.get("GenderID", 0)
        gender = "female" if gender_id == 2 else "male"

        is_new = self.graph_storage and self.graph_storage.get_node(node_id) is None

        node = {
            "id": node_id,
            "name": full_name,
            "label": "MK",
            "attributes": {
                "knesset_person_id": pid,
                "gender": gender,
                "email": person.get("Email", ""),
                "is_current_mk": bool(person.get("IsCurrent", False)),
                "faction": faction_name,
                "faction_id": faction_id,
                "positions": position_list,
                "knesset_numbers": sorted(knesset_numbers),
                "ideology_tags": ideology_tags,
            },
            "facts": [
                f"MK {full_name} (PersonID={pid})",
            ],
        }
        self.upsert_node(node)

        # Index in Pinecone for semantic search
        search_text = (
            f"{full_name}, Member of Knesset. "
            f"Faction: {faction_name}. "
            f"Knessets: {', '.join(str(k) for k in knesset_numbers)}."
        )
        self.index_in_pinecone(
            text=search_text,
            metadata={"id": node_id, "label": "MK", "name": full_name},
            namespace="knesset_members",
        )

        return bool(is_new)

    def _upsert_faction_node(self, faction: Dict[str, Any]) -> None:
        """Build and upsert a Faction node."""
        fid = faction.get("FactionID", 0)
        node_id = f"faction_{fid}"
        name = faction.get("Name", "")
        knesset_num = faction.get("KnessetNum", 0)

        ideology_tags: List[str] = []
        if name in RELIGIOUS_ZIONISM_FACTIONS:
            ideology_tags.append("religious_zionism")

        node = {
            "id": node_id,
            "name": name,
            "label": "Faction",
            "attributes": {
                "knesset_faction_id": fid,
                "knesset_num": knesset_num,
                "ideology_tags": ideology_tags,
            },
            "facts": [f"Faction '{name}' (FactionID={fid}, Knesset {knesset_num})"],
        }
        self.upsert_node(node)

    def _create_membership_edges(
        self,
        person_id: int,
        positions: List[Dict[str, Any]],
    ) -> None:
        """Create MEMBER_OF edges from MK → Faction for each unique faction."""
        seen_factions: Set[int] = set()
        for pos in positions:
            fid = pos.get("FactionID")
            if fid and fid not in seen_factions:
                seen_factions.add(fid)
                start_date = self.parse_odata_date(pos.get("StartDate"))
                finish_date = self.parse_odata_date(pos.get("FinishDate"))
                edge = {
                    "source_id": f"mk_{person_id}",
                    "target_id": f"faction_{fid}",
                    "relation": "MEMBER_OF",
                    "attributes": {
                        "knesset_num": pos.get("KnessetNum"),
                        "start_date": start_date,
                        "finish_date": finish_date,
                    },
                }
                self.upsert_edge(edge)
