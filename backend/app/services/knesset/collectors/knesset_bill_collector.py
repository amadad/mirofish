"""Knesset Bill / Legislation collector via OData API.

Fetches bills, their sponsors (initiators), and bill names from the
Knesset OData endpoint. Builds Bill nodes and PROPOSED edges to MKs.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.bills")

# Minimum Knesset number to collect (last 5-6 Knessets)
MIN_KNESSET_NUM = 20


class KnessetBillCollector(BaseKnessetCollector):
    """Collects legislative bill data from the Knesset OData API.

    Entities used:
        KNS_Bill          — bill metadata (ID, name, type, status, Knesset)
        KNS_BillInitiator — sponsors linking bills to persons
        KNS_BillName      — current and historical bill titles
    """

    SOURCE_ID = "knesset:odata:bills"

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
        last_bill_id = cursor_state.get("last_bill_id", 0)

        try:
            # 1. Fetch bills -------------------------------------------
            bills = self._fetch_bills(last_bill_id)
            if not bills:
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    new_cursor=cursor_state,
                    duration_seconds=time.time() - start,
                )

            bill_ids = [b.get("BillID", 0) for b in bills]
            max_bill_id = max(bill_ids) if bill_ids else last_bill_id

            # 2. Fetch initiators for those bills ----------------------
            initiators = self._fetch_initiators(bill_ids)
            initiators_by_bill = self._group_initiators_by_bill(initiators)

            # 3. Fetch bill names for richer titles --------------------
            bill_names = self._fetch_bill_names(bill_ids)
            names_by_bill = self._group_names_by_bill(bill_names)

            # 4. Build and upsert nodes / edges ------------------------
            new_count = 0
            updated_count = 0

            for bill in bills:
                bid = bill.get("BillID", 0)
                bill_initiators = initiators_by_bill.get(bid, [])
                bill_name_records = names_by_bill.get(bid, [])

                was_new = self._upsert_bill_node(
                    bill, bill_initiators, bill_name_records,
                )
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # PROPOSED edges: MK → Bill
                self._create_proposed_edges(bid, bill_initiators)

            new_cursor = {"last_bill_id": max_bill_id}

            logger.info(
                "%s: collected %d bills (%d new, %d updated)",
                self.get_source_id(),
                len(bills),
                new_count,
                updated_count,
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

    def _fetch_bills(self, last_bill_id: int) -> List[Dict[str, Any]]:
        """Fetch bills from Knessets >= MIN_KNESSET_NUM with incremental cursor."""
        odata_filter = (
            f"KnessetNum ge {MIN_KNESSET_NUM} and BillID gt {last_bill_id}"
        )
        bills = self.fetch_odata_all(
            "KNS_Bill",
            params={
                "$filter": odata_filter,
                "$orderby": "BillID asc",
            },
            page_size=200,
            max_pages=200,
        )
        logger.info(
            "%s: fetched %d bills (after BillID=%d)",
            self.get_source_id(),
            len(bills),
            last_bill_id,
        )
        return bills

    def _fetch_initiators(
        self, bill_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """Fetch KNS_BillInitiator rows for a set of bill IDs."""
        all_initiators: List[Dict[str, Any]] = []
        batch_size = 50
        for i in range(0, len(bill_ids), batch_size):
            batch = bill_ids[i : i + batch_size]
            filter_parts = " or ".join(f"BillID eq {bid}" for bid in batch)
            rows = self.fetch_odata_all(
                "KNS_BillInitiator",
                params={"$filter": filter_parts},
                page_size=500,
            )
            all_initiators.extend(rows)
        logger.info(
            "%s: fetched %d initiator records",
            self.get_source_id(),
            len(all_initiators),
        )
        return all_initiators

    def _fetch_bill_names(
        self, bill_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """Fetch KNS_BillName rows for a set of bill IDs."""
        all_names: List[Dict[str, Any]] = []
        batch_size = 50
        for i in range(0, len(bill_ids), batch_size):
            batch = bill_ids[i : i + batch_size]
            filter_parts = " or ".join(f"BillID eq {bid}" for bid in batch)
            rows = self.fetch_odata_all(
                "KNS_BillName",
                params={"$filter": filter_parts},
                page_size=500,
            )
            all_names.extend(rows)
        return all_names

    # ------------------------------------------------------------------
    # Data transformation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_initiators_by_bill(
        initiators: List[Dict[str, Any]],
    ) -> Dict[int, List[Dict[str, Any]]]:
        grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in initiators:
            grouped[row.get("BillID", 0)].append(row)
        return dict(grouped)

    @staticmethod
    def _group_names_by_bill(
        names: List[Dict[str, Any]],
    ) -> Dict[int, List[Dict[str, Any]]]:
        grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in names:
            grouped[row.get("BillID", 0)].append(row)
        return dict(grouped)

    @staticmethod
    def _resolve_bill_name(
        bill: Dict[str, Any],
        name_records: List[Dict[str, Any]],
    ) -> str:
        """Pick the best bill name: prefer KNS_BillName, fall back to KNS_Bill.Name."""
        if name_records:
            # Prefer the most recent name entry
            for rec in sorted(
                name_records,
                key=lambda r: r.get("BillNameID", 0),
                reverse=True,
            ):
                name = rec.get("Name", "")
                if name:
                    return name
        return bill.get("Name", f"Bill #{bill.get('BillID', '?')}")

    # ------------------------------------------------------------------
    # Node / edge upsert
    # ------------------------------------------------------------------

    def _upsert_bill_node(
        self,
        bill: Dict[str, Any],
        initiators: List[Dict[str, Any]],
        name_records: List[Dict[str, Any]],
    ) -> bool:
        """Build and upsert a Bill node. Returns True if the node was new."""
        bid = bill.get("BillID", 0)
        node_id = f"bill_{bid}"
        bill_name = self._resolve_bill_name(bill, name_records)

        # Determine bill type from SubTypeDesc
        bill_type = (bill.get("SubTypeDesc") or "").strip()

        # Build initiator MK ID list
        mk_ids: List[str] = []
        first_initiators: List[str] = []
        for init in initiators:
            pid = init.get("PersonID", 0)
            mk_id = f"mk_{pid}"
            mk_ids.append(mk_id)
            if init.get("IsFirstInitiator"):
                first_initiators.append(mk_id)

        is_new = self.graph_storage and self.graph_storage.get_node(node_id) is None

        node = {
            "id": node_id,
            "name": bill_name,
            "label": "Bill",
            "attributes": {
                "knesset_bill_id": bid,
                "knesset_num": bill.get("KnessetNum", 0),
                "bill_type": bill_type,
                "status": bill.get("StatusID"),
                "private_number": bill.get("PrivateNumber"),
                "initiators": mk_ids,
                "first_initiators": first_initiators,
            },
            "facts": [
                f"Bill '{bill_name}' (BillID={bid}, Knesset {bill.get('KnessetNum', '?')})",
            ],
        }
        self.upsert_node(node)

        # Index in Pinecone
        search_text = (
            f"Bill: {bill_name}. "
            f"Type: {bill_type}. "
            f"Knesset: {bill.get('KnessetNum', '')}. "
            f"Sponsors: {len(mk_ids)}."
        )
        self.index_in_pinecone(
            text=search_text,
            metadata={"id": node_id, "label": "Bill", "name": bill_name},
            namespace="knesset_bills",
        )

        return bool(is_new)

    def _create_proposed_edges(
        self,
        bill_id: int,
        initiators: List[Dict[str, Any]],
    ) -> None:
        """Create PROPOSED edges from each initiating MK → Bill."""
        bill_node_id = f"bill_{bill_id}"
        seen_persons: Set[int] = set()

        for init in initiators:
            pid = init.get("PersonID", 0)
            if pid and pid not in seen_persons:
                seen_persons.add(pid)
                edge = {
                    "source_id": f"mk_{pid}",
                    "target_id": bill_node_id,
                    "relation": "PROPOSED",
                    "attributes": {
                        "is_first_initiator": bool(init.get("IsFirstInitiator")),
                    },
                }
                self.upsert_edge(edge)
