"""Base collector for Knesset data sources.

All collectors inherit from BaseKnessetCollector and implement
collect_incremental() for paginated/incremental data fetching.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector")


class BaseKnessetCollector(ABC):
    """Abstract base for all Knesset data collectors."""

    # Subclass config
    SOURCE_ID: str = ""
    RATE_LIMIT_SECONDS: float = 0.5
    MAX_RETRIES: int = 3
    RETRY_BACKOFF: float = 2.0
    REQUEST_TIMEOUT: int = 30

    def __init__(
        self,
        graph_storage=None,
        pinecone_service=None,
    ):
        self.graph_storage = graph_storage
        self.pinecone_service = pinecone_service
        self._session: Optional[requests.Session] = None
        self._last_request_time: float = 0

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": "MiroFish-KnessetDB/1.0 (research)",
                "Accept": "application/json",
            })
        return self._session

    @abstractmethod
    def get_source_id(self) -> str:
        """Return the unique source identifier (e.g. 'knesset:odata:members')."""
        ...

    @abstractmethod
    def collect_incremental(
        self, cursor_state: Optional[Dict[str, Any]] = None
    ) -> CollectionResult:
        """Fetch new data since the last cursor position.

        Args:
            cursor_state: Previous pagination/offset state (None for first run).

        Returns:
            CollectionResult with item counts and new cursor state.
        """
        ...

    # ------------------------------------------------------------------
    # HTTP helpers with rate limiting and retries
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_SECONDS:
            time.sleep(self.RATE_LIMIT_SECONDS - elapsed)
        self._last_request_time = time.time()

    def fetch_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
    ) -> Optional[Dict[str, Any]]:
        """Fetch JSON from URL with rate limiting and retries.

        Returns parsed JSON dict or None on failure.
        """
        self._rate_limit()
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                if method == "GET":
                    resp = self.session.get(
                        url, params=params, timeout=self.REQUEST_TIMEOUT
                    )
                else:
                    resp = self.session.post(
                        url, json=params, timeout=self.REQUEST_TIMEOUT
                    )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 429:
                    # Rate limited — back off harder
                    wait = self.RETRY_BACKOFF ** (attempt + 2)
                    logger.warning(
                        "%s: rate limited, waiting %.1fs",
                        self.get_source_id(), wait,
                    )
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = self.RETRY_BACKOFF ** (attempt + 1)
                    logger.warning(
                        "%s: server error %d, retry %d/%d in %.1fs",
                        self.get_source_id(), resp.status_code,
                        attempt + 1, self.MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue

                # 4xx — don't retry
                logger.error(
                    "%s: HTTP %d for %s",
                    self.get_source_id(), resp.status_code, url,
                )
                return None

            except requests.RequestException as e:
                last_error = str(e)
                wait = self.RETRY_BACKOFF ** (attempt + 1)
                logger.warning(
                    "%s: request error: %s, retry %d/%d in %.1fs",
                    self.get_source_id(), e,
                    attempt + 1, self.MAX_RETRIES, wait,
                )
                time.sleep(wait)

        logger.error(
            "%s: exhausted retries for %s (last error: %s)",
            self.get_source_id(), url, last_error,
        )
        return None

    def fetch_text(self, url: str) -> Optional[str]:
        """Fetch raw text content (for protocol documents, CSVs, etc.)."""
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            logger.error("%s: HTTP %d for %s", self.get_source_id(), resp.status_code, url)
        except requests.RequestException as e:
            logger.error("%s: request error: %s", self.get_source_id(), e)
        return None

    # ------------------------------------------------------------------
    # Graph storage helpers
    # ------------------------------------------------------------------

    def upsert_node(self, node: Dict[str, Any]) -> None:
        """Insert or update a node in the graph."""
        if self.graph_storage is None:
            return
        existing = self.graph_storage.get_node(node["id"])
        if existing:
            # Merge attributes
            merged_attrs = {**existing.get("attributes", {}), **node.get("attributes", {})}
            node["attributes"] = merged_attrs
            # Merge facts
            existing_facts = set(existing.get("facts", []))
            new_facts = node.get("facts", [])
            node["facts"] = list(existing_facts | set(new_facts))
            self.graph_storage.update_node(node["id"], node)
        else:
            self.graph_storage.add_node(node)

    def upsert_edge(self, edge: Dict[str, Any]) -> bool:
        """Insert or update an edge in the graph.

        Returns True if edge was created, False if skipped/failed.
        Gracefully handles missing source/target nodes.
        """
        if self.graph_storage is None:
            return False
        try:
            # Check if edge already exists
            existing = self.graph_storage.get_edges(
                source_id=edge.get("source_id"),
                target_id=edge.get("target_id"),
                relation=edge.get("relation"),
            )
            if not existing:
                self.graph_storage.add_edge(edge)
                return True
        except Exception as e:
            # StorageError for missing nodes, etc. — log and skip
            logger.debug(
                "Edge skipped (%s -> %s [%s]): %s",
                edge.get("source_id", "?"),
                edge.get("target_id", "?"),
                edge.get("relation", "?"),
                e,
            )
        return False

    def index_in_pinecone(
        self, text: str, metadata: Dict[str, Any], namespace: str
    ) -> None:
        """Index a text document in Pinecone for semantic search.

        Uses PineconeSearchService.index_nodes() which handles embeddings.
        """
        if self.pinecone_service is None or not self.pinecone_service.is_available:
            return
        try:
            node = {
                "id": metadata.get("id", ""),
                "name": metadata.get("name", metadata.get("name_he", "")),
                "label": metadata.get("entity_type", metadata.get("label", "")),
                "summary": text[:2000],
                "facts": [],
                "attributes": {k: v for k, v in metadata.items()
                               if isinstance(v, (str, int, float, bool))},
            }
            self.pinecone_service.index_nodes("knesset", [node])
        except Exception as e:
            logger.warning("Pinecone indexing failed: %s", e)

    # ------------------------------------------------------------------
    # Knesset OData helpers
    # ------------------------------------------------------------------

    KNESSET_ODATA_BASE = "https://knesset.gov.il/Odata/ParliamentInfo.svc"

    def fetch_odata(
        self,
        entity: str,
        params: Optional[Dict[str, str]] = None,
        skip: int = 0,
        top: int = 100,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch from Knesset OData API with pagination.

        Returns list of result items, or None on failure.
        """
        url = f"{self.KNESSET_ODATA_BASE}/{entity}"
        query: Dict[str, str] = {"$format": "json", "$top": str(top)}
        if skip > 0:
            query["$skip"] = str(skip)
        if params:
            query.update(params)

        data = self.fetch_json(url, params=query)
        if data is None:
            return None

        # OData v2 wraps in { d: { results: [...] } }
        # OData v4 uses { value: [...] }
        if "d" in data:
            results = data["d"]
            if isinstance(results, dict) and "results" in results:
                return results["results"]
            if isinstance(results, list):
                return results
        if "value" in data:
            return data["value"]

        return None

    def fetch_odata_all(
        self,
        entity: str,
        params: Optional[Dict[str, str]] = None,
        page_size: int = 100,
        max_pages: int = 100,
    ) -> List[Dict[str, Any]]:
        """Fetch all pages from Knesset OData endpoint.

        Handles manual pagination since the API doesn't return nextLink.
        """
        all_items: List[Dict[str, Any]] = []
        for page in range(max_pages):
            skip = page * page_size
            items = self.fetch_odata(entity, params, skip=skip, top=page_size)
            if items is None:
                break
            all_items.extend(items)
            if len(items) < page_size:
                break  # Last page
            logger.info(
                "%s: fetched page %d (%d items, %d total)",
                self.get_source_id(), page + 1, len(items), len(all_items),
            )
        return all_items

    # ------------------------------------------------------------------
    # Utility: OData date parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_odata_date(date_str: Optional[str]) -> Optional[str]:
        """Parse OData date format /Date(ms)/ to ISO string."""
        if not date_str:
            return None
        import re
        m = re.search(r"/Date\((\d+)\)/", str(date_str))
        if m:
            from datetime import datetime, timezone
            ts = int(m.group(1)) / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        # Already ISO?
        if isinstance(date_str, str) and len(date_str) >= 10:
            return date_str[:10]
        return None

    def close(self) -> None:
        """Clean up resources."""
        if self._session:
            self._session.close()
            self._session = None
