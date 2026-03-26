"""Knesset Committee collector via OData API.

Fetches committee data, session items, and committee memberships
to build Committee nodes and SITS_ON edges from MKs to Committees.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.committees")

# Knesset numbers to cover (20th-25th)
KNESSET_RANGE = range(20, 26)


class KnessetCommitteeCollector(BaseKnessetCollector):
    """Collects Knesset committee data from the OData API.

    Entities used:
        KNS_Committee        - CommitteeID, Name, CategoryDesc, KnessetNum
        KNS_CmtSessionItem   - SessionID, CommitteeID, Name, StartDate
        KNS_CmtSiteMember    - CommitteeID, PersonID (for SITS_ON edges)
    """

    SOURCE_ID = "knesset:odata:committees"

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
        last_committee_id = cursor_state.get("last_committee_id", 0)
        last_session_id = cursor_state.get("last_session_id", 0)

        try:
            # 1. Fetch committees ----------------------------------------
            committees = self._fetch_committees(last_committee_id)
            if not committees:
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    new_cursor=cursor_state,
                    duration_seconds=time.time() - start,
                )

            committee_ids = [c.get("CommitteeID", 0) for c in committees]
            max_committee_id = max(committee_ids) if committee_ids else last_committee_id

            # 2. Fetch committee members ---------------------------------
            members_by_committee = self._fetch_committee_members(committee_ids)

            # 3. Fetch recent session items ------------------------------
            sessions, max_session_id = self._fetch_session_items(
                committee_ids, last_session_id,
            )

            # 4. Build and upsert nodes / edges --------------------------
            new_count = 0
            updated_count = 0

            for committee in committees:
                cid = committee.get("CommitteeID", 0)
                was_new = self._upsert_committee_node(committee)
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Create SITS_ON edges from MK -> Committee
                for member in members_by_committee.get(cid, []):
                    self._create_sits_on_edge(member, cid)

            new_cursor = {
                "last_committee_id": max_committee_id,
                "last_session_id": max_session_id or last_session_id,
            }

            logger.info(
                "%s: collected %d committees (%d new, %d updated), %d sessions",
                self.get_source_id(),
                len(committees),
                new_count,
                updated_count,
                len(sessions),
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

    def _fetch_committees(self, last_committee_id: int) -> List[Dict[str, Any]]:
        """Fetch committees from recent Knessets, incrementally."""
        all_committees: List[Dict[str, Any]] = []
        seen_ids: Set[int] = set()

        for knum in KNESSET_RANGE:
            odata_filter = (
                f"KnessetNum eq {knum} and CommitteeID gt {last_committee_id}"
            )
            items = self.fetch_odata_all(
                "KNS_Committee",
                params={"$filter": odata_filter},
            )
            for item in items:
                cid = item.get("CommitteeID", 0)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    all_committees.append(item)

        logger.info(
            "%s: fetched %d committees across Knessets %d-%d",
            self.get_source_id(),
            len(all_committees),
            KNESSET_RANGE.start,
            KNESSET_RANGE.stop - 1,
        )
        return all_committees

    def _fetch_committee_members(
        self, committee_ids: List[int],
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Fetch committee members via KNS_PersonToPosition.

        KNS_CmtSiteMember doesn't exist in the API — committee membership
        is inferred from positions where DutyDesc contains committee names.
        We skip this step if the data isn't available and rely on the
        member collector to build SITS_ON edges from position data.
        """
        # Committee member data comes from positions, not a dedicated entity.
        # The member collector handles SITS_ON edges, so we return empty here.
        logger.debug(
            "%s: committee member assignment delegated to member collector",
            self.get_source_id(),
        )
        return {}

    def _fetch_session_items(
        self,
        committee_ids: List[int],
        last_session_id: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Fetch recent session items for tracked committees.

        Returns (sessions_list, max_session_id).
        """
        all_sessions: List[Dict[str, Any]] = []
        max_sid = last_session_id
        batch_size = 30

        # Fetch session items with simple filter (avoid complex OR filters that cause 400)
        for entity in ("KNS_CommitteeSession", "KNS_CmtSessionItem"):
            odata_filter = f"CommitteeSessionID gt {last_session_id}"
            if entity == "KNS_CmtSessionItem":
                odata_filter = f"CmtSessionItemID gt {last_session_id}"
            items = self.fetch_odata_all(
                entity,
                params={
                    "$filter": odata_filter,
                    "$orderby": odata_filter.split(" gt")[0] + " asc",
                },
                page_size=100,
                max_pages=10,
            )
            if items:
                all_sessions.extend(items)
                break
            for item in items:
                sid = item.get("CmtSessionItemID", 0)
                if sid > max_sid:
                    max_sid = sid

        logger.info(
            "%s: fetched %d session items",
            self.get_source_id(),
            len(all_sessions),
        )
        return all_sessions, max_sid

    # ------------------------------------------------------------------
    # Node / edge upsert
    # ------------------------------------------------------------------

    def _upsert_committee_node(self, committee: Dict[str, Any]) -> bool:
        """Build and upsert a Committee node. Returns True if new."""
        cid = committee.get("CommitteeID", 0)
        node_id = f"committee_{cid}"
        name = committee.get("Name", "")
        category = committee.get("CategoryDesc", "")
        knesset_num = committee.get("KnessetNum", 0)

        is_new = self.graph_storage and self.graph_storage.get_node(node_id) is None

        node = {
            "id": node_id,
            "name": name,
            "label": "Committee",
            "attributes": {
                "knesset_committee_id": cid,
                "category": category,
                "knesset_num": knesset_num,
                "parent_committee_id": committee.get("ParentCommitteeID"),
                "is_special": bool(committee.get("AdditionalTypeDesc")),
            },
            "facts": [
                f"Committee '{name}' (ID={cid}, Knesset {knesset_num}, {category})",
            ],
        }
        self.upsert_node(node)

        # Index for semantic search
        search_text = (
            f"Knesset Committee: {name}. "
            f"Category: {category}. Knesset {knesset_num}."
        )
        self.index_in_pinecone(
            text=search_text,
            metadata={"id": node_id, "label": "Committee", "name": name},
            namespace="knesset_committees",
        )

        return bool(is_new)

    def _create_sits_on_edge(
        self, member: Dict[str, Any], committee_id: int,
    ) -> None:
        """Create a SITS_ON edge from an MK to a Committee."""
        person_id = member.get("PersonID")
        if not person_id:
            return

        start_date = self.parse_odata_date(member.get("StartDate"))
        finish_date = self.parse_odata_date(member.get("FinishDate"))

        edge = {
            "source_id": f"mk_{person_id}",
            "target_id": f"committee_{committee_id}",
            "relation": "SITS_ON",
            "attributes": {
                "start_date": start_date,
                "finish_date": finish_date,
                "is_chairperson": bool(member.get("IsChairPerson")),
            },
        }
        self.upsert_edge(edge)
