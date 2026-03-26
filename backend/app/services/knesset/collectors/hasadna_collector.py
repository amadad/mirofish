"""Hasadna (The Public Knowledge Workshop) data pipeline collector.

Downloads CSV bulk data from Hasadna's Knesset data pipelines hosted
on Google Cloud Storage. Good for historical cross-validation and
bulk entity creation.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.hasadna")

HASADNA_STORAGE_BASE = (
    "https://storage.googleapis.com/knesset-data-pipelines/data"
)

# Available CSV datasets
DATASETS = {
    "members": f"{HASADNA_STORAGE_BASE}/members/all.csv",
    "bills": f"{HASADNA_STORAGE_BASE}/bills/all.csv",
    "votes": f"{HASADNA_STORAGE_BASE}/votes/all.csv",
}


class HasadnaCollector(BaseKnessetCollector):
    """Collects bulk historical data from Hasadna data pipelines.

    Source: https://storage.googleapis.com/knesset-data-pipelines/data/
    Downloads CSV files for members, bills, and votes and uses them
    to create or cross-validate existing graph entities.
    """

    SOURCE_ID = "hasadna:pipelines"
    RATE_LIMIT_SECONDS = 1.0
    REQUEST_TIMEOUT = 60  # CSVs can be large

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
        # Track which datasets have been processed
        completed_datasets = set(cursor_state.get("completed", []))
        pending = [d for d in DATASETS if d not in completed_datasets]

        if not pending:
            # All datasets processed — reset for next full cycle
            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=0,
                items_updated=0,
                new_cursor={"completed": []},
                duration_seconds=time.time() - start,
            )

        try:
            total_new = 0
            total_updated = 0

            # Process one dataset per incremental call to avoid timeouts
            dataset_name = pending[0]
            url = DATASETS[dataset_name]

            logger.info(
                "%s: downloading %s dataset from %s",
                self.get_source_id(),
                dataset_name,
                url,
            )

            csv_text = self.fetch_text(url)
            if csv_text is None:
                logger.warning(
                    "%s: failed to download %s, skipping",
                    self.get_source_id(),
                    dataset_name,
                )
                completed_datasets.add(dataset_name)
                return CollectionResult(
                    source_id=self.get_source_id(),
                    error=f"Failed to download {dataset_name} CSV",
                    new_cursor={"completed": list(completed_datasets)},
                    duration_seconds=time.time() - start,
                )

            rows = self._parse_csv(csv_text)
            logger.info(
                "%s: parsed %d rows from %s",
                self.get_source_id(),
                len(rows),
                dataset_name,
            )

            if dataset_name == "members":
                new, updated = self._process_members(rows)
            elif dataset_name == "bills":
                new, updated = self._process_bills(rows)
            elif dataset_name == "votes":
                new, updated = self._process_votes(rows)
            else:
                new, updated = 0, 0

            total_new += new
            total_updated += updated
            completed_datasets.add(dataset_name)

            logger.info(
                "%s: %s — %d new, %d updated",
                self.get_source_id(),
                dataset_name,
                new,
                updated,
            )

            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=total_new,
                items_updated=total_updated,
                new_cursor={"completed": list(completed_datasets)},
                duration_seconds=time.time() - start,
            )

        except Exception as exc:
            logger.exception("%s: collection failed", self.get_source_id())
            return CollectionResult(
                source_id=self.get_source_id(),
                error=str(exc),
                new_cursor={"completed": list(completed_datasets)},
                duration_seconds=time.time() - start,
            )

    # ------------------------------------------------------------------
    # CSV parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_csv(text: str) -> List[Dict[str, str]]:
        """Parse CSV text into list of row dicts."""
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    # ------------------------------------------------------------------
    # Dataset processors
    # ------------------------------------------------------------------

    def _process_members(
        self, rows: List[Dict[str, str]],
    ) -> tuple[int, int]:
        """Process members CSV and enrich/create MK nodes.

        Returns (new_count, updated_count).
        """
        new_count = 0
        updated_count = 0

        for row in rows:
            mk_id = row.get("id") or row.get("mk_individual_id")
            if not mk_id:
                continue

            node_id = f"mk_{mk_id}"
            name = row.get("name", "") or row.get("mk_individual_name", "")

            is_new = (
                self.graph_storage
                and self.graph_storage.get_node(node_id) is None
            )

            node = {
                "id": node_id,
                "name": name,
                "label": "MK",
                "attributes": {
                    "hasadna_id": mk_id,
                    "hasadna_validated": True,
                },
                "facts": [],
            }

            # Map available CSV columns to attributes
            if row.get("party"):
                node["attributes"]["hasadna_party"] = row["party"]
            if row.get("start_date"):
                node["attributes"]["hasadna_start_date"] = row["start_date"]
            if row.get("end_date"):
                node["attributes"]["hasadna_end_date"] = row["end_date"]
            if row.get("knesset_num"):
                node["attributes"]["hasadna_knesset_num"] = row["knesset_num"]
            if row.get("gender"):
                node["attributes"]["gender"] = row["gender"]

            self.upsert_node(node)
            if is_new:
                new_count += 1
            else:
                updated_count += 1

        return new_count, updated_count

    def _process_bills(
        self, rows: List[Dict[str, str]],
    ) -> tuple[int, int]:
        """Process bills CSV and enrich/create Bill nodes.

        Returns (new_count, updated_count).
        """
        new_count = 0
        updated_count = 0

        for row in rows:
            bill_id = row.get("id") or row.get("BillID")
            if not bill_id:
                continue

            node_id = f"bill_{bill_id}"
            name = row.get("name") or row.get("KNS_BillName", "")

            is_new = (
                self.graph_storage
                and self.graph_storage.get_node(node_id) is None
            )

            node = {
                "id": node_id,
                "name": name,
                "label": "Bill",
                "attributes": {
                    "hasadna_id": bill_id,
                    "hasadna_validated": True,
                },
                "facts": [],
            }

            if row.get("status"):
                node["attributes"]["hasadna_status"] = row["status"]
            if row.get("date"):
                node["attributes"]["hasadna_date"] = row["date"]
            if row.get("proposer"):
                node["attributes"]["hasadna_proposer"] = row["proposer"]
            if row.get("knesset_num"):
                node["attributes"]["hasadna_knesset_num"] = row["knesset_num"]

            self.upsert_node(node)
            if is_new:
                new_count += 1
            else:
                updated_count += 1

        return new_count, updated_count

    def _process_votes(
        self, rows: List[Dict[str, str]],
    ) -> tuple[int, int]:
        """Process votes CSV and create Vote nodes.

        Returns (new_count, updated_count).
        """
        new_count = 0
        updated_count = 0

        for row in rows:
            vote_id = row.get("id") or row.get("vote_id")
            if not vote_id:
                continue

            node_id = f"vote_{vote_id}"

            is_new = (
                self.graph_storage
                and self.graph_storage.get_node(node_id) is None
            )

            node = {
                "id": node_id,
                "name": row.get("title", f"Vote {vote_id}"),
                "label": "Vote",
                "attributes": {
                    "hasadna_id": vote_id,
                    "hasadna_validated": True,
                },
                "facts": [],
            }

            if row.get("date"):
                node["attributes"]["vote_date"] = row["date"]
            if row.get("result"):
                node["attributes"]["vote_result"] = row["result"]
            if row.get("for_votes"):
                node["attributes"]["for_votes"] = int(row["for_votes"])
            if row.get("against_votes"):
                node["attributes"]["against_votes"] = int(row["against_votes"])

            # Link vote to bill if available
            bill_id = row.get("bill_id")
            if bill_id:
                node["attributes"]["bill_id"] = bill_id
                edge = {
                    "source_id": node_id,
                    "target_id": f"bill_{bill_id}",
                    "relation": "VOTE_ON",
                    "attributes": {"date": row.get("date", "")},
                }
                self.upsert_edge(edge)

            self.upsert_node(node)
            if is_new:
                new_count += 1
            else:
                updated_count += 1

        return new_count, updated_count
