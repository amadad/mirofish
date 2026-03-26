"""Israel Government Data Portal (data.gov.il) collector.

Searches and downloads Knesset-related datasets from Israel's
open data portal, which uses the CKAN API format.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.datagov")

DATAGOV_API_BASE = "https://data.gov.il/api/3/action"
DATAGOV_SEARCH_URL = f"{DATAGOV_API_BASE}/package_search"
DATAGOV_RESOURCE_URL = f"{DATAGOV_API_BASE}/datastore_search"

# Search queries for relevant datasets
SEARCH_QUERIES = [
    "כנסת",             # Knesset
    "תקציב המדינה",     # State budget
    "חברי כנסת",         # MKs
    "הצבעות",           # Votes
    "חקיקה",            # Legislation
]

# Maximum resources to process per dataset
MAX_RESOURCES_PER_DATASET = 3


class DataGovCollector(BaseKnessetCollector):
    """Collects Knesset-related data from Israel's Government Data Portal.

    API: https://data.gov.il/api/3/action/package_search (CKAN format)
    Searches for Knesset-related datasets including budget, legislation,
    and demographic data relevant to parliamentary analysis.
    """

    SOURCE_ID = "datagov:datasets"
    RATE_LIMIT_SECONDS = 1.0
    REQUEST_TIMEOUT = 45

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
        query_index = cursor_state.get("query_index", 0)
        last_offset = cursor_state.get("offset", 0)

        if query_index >= len(SEARCH_QUERIES):
            # All queries exhausted — reset
            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=0,
                items_updated=0,
                new_cursor={"query_index": 0, "offset": 0},
                duration_seconds=time.time() - start,
            )

        try:
            query = SEARCH_QUERIES[query_index]
            new_count = 0
            updated_count = 0

            # Search for datasets matching the query
            datasets = self._search_datasets(query, offset=last_offset)
            if not datasets:
                # Move to next query
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    new_cursor={"query_index": query_index + 1, "offset": 0},
                    duration_seconds=time.time() - start,
                )

            for dataset in datasets:
                ds_new, ds_updated = self._process_dataset(dataset)
                new_count += ds_new
                updated_count += ds_updated

            # If we got a full page, there may be more
            page_size = 10
            if len(datasets) >= page_size:
                new_cursor = {
                    "query_index": query_index,
                    "offset": last_offset + page_size,
                }
            else:
                new_cursor = {
                    "query_index": query_index + 1,
                    "offset": 0,
                }

            logger.info(
                "%s: query '%s' — %d datasets, %d new items, %d updated",
                self.get_source_id(),
                query,
                len(datasets),
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
    # CKAN API helpers
    # ------------------------------------------------------------------

    def _search_datasets(
        self, query: str, offset: int = 0, rows: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search data.gov.il for datasets matching query."""
        data = self.fetch_json(
            DATAGOV_SEARCH_URL,
            params={"q": query, "start": str(offset), "rows": str(rows)},
        )
        if not data:
            return []

        result = data.get("result", {})
        return result.get("results", [])

    def _fetch_resource_data(
        self, resource_id: str, limit: int = 100, offset: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Fetch rows from a CKAN datastore resource."""
        return self.fetch_json(
            DATAGOV_RESOURCE_URL,
            params={
                "resource_id": resource_id,
                "limit": str(limit),
                "offset": str(offset),
            },
        )

    # ------------------------------------------------------------------
    # Dataset processing
    # ------------------------------------------------------------------

    def _process_dataset(
        self, dataset: Dict[str, Any],
    ) -> tuple[int, int]:
        """Process a single CKAN dataset and its resources.

        Creates a Dataset node and processes up to MAX_RESOURCES_PER_DATASET
        resources for relevant data.

        Returns (new_count, updated_count).
        """
        ds_id = dataset.get("id", "")
        ds_name = dataset.get("title", "") or dataset.get("name", "")
        if not ds_id:
            return 0, 0

        node_id = f"datagov_{ds_id[:12]}"

        is_new = (
            self.graph_storage
            and self.graph_storage.get_node(node_id) is None
        )

        # Create/update Dataset node
        node = {
            "id": node_id,
            "name": ds_name,
            "label": "Dataset",
            "attributes": {
                "datagov_id": ds_id,
                "organization": dataset.get("organization", {}).get("title", ""),
                "notes": (dataset.get("notes", "") or "")[:500],
                "num_resources": dataset.get("num_resources", 0),
                "metadata_modified": dataset.get("metadata_modified", ""),
                "license": dataset.get("license_title", ""),
                "tags": [
                    t.get("display_name", "")
                    for t in dataset.get("tags", [])
                ],
            },
            "facts": [
                f"Dataset '{ds_name}' from data.gov.il (ID={ds_id[:12]})",
            ],
        }
        self.upsert_node(node)

        # Index for semantic search
        search_text = (
            f"Government dataset: {ds_name}. "
            f"{(dataset.get('notes', '') or '')[:200]}"
        )
        self.index_in_pinecone(
            text=search_text,
            metadata={"id": node_id, "label": "Dataset", "name": ds_name},
            namespace="knesset_datasets",
        )

        # Process resources (actual data files)
        new_count = 1 if is_new else 0
        updated_count = 0 if is_new else 1

        resources = dataset.get("resources", [])[:MAX_RESOURCES_PER_DATASET]
        for resource in resources:
            r_new, r_upd = self._process_resource(resource, node_id)
            new_count += r_new
            updated_count += r_upd

        return new_count, updated_count

    def _process_resource(
        self,
        resource: Dict[str, Any],
        parent_node_id: str,
    ) -> tuple[int, int]:
        """Process a single CKAN resource (data file).

        For datastore-enabled resources, fetches sample rows.
        Returns (new_count, updated_count).
        """
        resource_id = resource.get("id", "")
        resource_format = (resource.get("format", "") or "").upper()

        if not resource_id:
            return 0, 0

        # Only process datastore-enabled (API-accessible) resources
        if not resource.get("datastore_active", False):
            return 0, 0

        data = self._fetch_resource_data(resource_id, limit=50)
        if not data or "result" not in data:
            return 0, 0

        result = data["result"]
        records = result.get("records", [])
        fields = result.get("fields", [])

        if not records:
            return 0, 0

        # Store a summary of the resource content
        resource_node_id = f"datagov_res_{resource_id[:12]}"
        is_new = (
            self.graph_storage
            and self.graph_storage.get_node(resource_node_id) is None
        )

        field_names = [f.get("id", "") for f in fields if f.get("id") != "_id"]
        resource_name = resource.get("name", "") or resource.get("description", "")

        node = {
            "id": resource_node_id,
            "name": resource_name or f"Resource {resource_id[:8]}",
            "label": "DataResource",
            "attributes": {
                "datagov_resource_id": resource_id,
                "format": resource_format,
                "fields": field_names[:20],  # Cap field list
                "total_records": result.get("total", 0),
                "sample_size": len(records),
            },
            "facts": [],
        }
        self.upsert_node(node)

        # Link resource to its parent dataset
        edge = {
            "source_id": parent_node_id,
            "target_id": resource_node_id,
            "relation": "CONTAINS_RESOURCE",
            "attributes": {"format": resource_format},
        }
        self.upsert_edge(edge)

        return (1, 0) if is_new else (0, 1)
