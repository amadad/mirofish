"""Collector for Israeli government budget data from next.obudget.org.

Fetches budget lines, government supports/grants, and tenders via the
Open Budget API.  Supports incremental collection with cursor-based
pagination and stores results as KuzuDB graph nodes with hierarchy edges.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.obudget")

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

BASE_URL = "https://next.obudget.org/api"
SEARCH_BUDGET_URL = f"{BASE_URL}/search/budget"
# obudget.org uses /search/<doc_type> — supports and tenders use these paths:
SEARCH_SUPPORTS_URL = f"{BASE_URL}/search/gov_social_service_unit"
SEARCH_TENDERS_URL = f"{BASE_URL}/search/procurement"
QUERY_URL = f"{BASE_URL}/query"

VALID_SUB_SOURCES = ("budgets", "supports", "tenders")

# Israeli budget top-level codes are two-digit ministry prefixes (00–99).
# In practice only a subset exist; we probe all and skip empty results.
MINISTRY_CODE_RANGE = range(0, 100)

DEFAULT_PAGE_SIZE = 100
MAX_PAGES_PER_RUN = 50  # safety cap per incremental run


class OBudgetCollector(BaseKnessetCollector):
    """Collects Israeli government budget data from next.obudget.org.

    Parameters
    ----------
    sub_source : str
        One of ``"budgets"``, ``"supports"``, or ``"tenders"``.
    graph_storage, pinecone_service :
        Passed through to ``BaseKnessetCollector``.
    """

    RATE_LIMIT_SECONDS: float = 1.0  # 1 req/s as required

    def __init__(
        self,
        sub_source: str = "budgets",
        graph_storage=None,
        pinecone_service=None,
    ):
        if sub_source not in VALID_SUB_SOURCES:
            raise ValueError(
                f"sub_source must be one of {VALID_SUB_SOURCES}, got {sub_source!r}"
            )
        super().__init__(
            graph_storage=graph_storage,
            pinecone_service=pinecone_service,
        )
        self.sub_source = sub_source

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def get_source_id(self) -> str:
        return f"obudget:{self.sub_source}"

    def collect_incremental(
        self, cursor_state: Optional[Dict[str, Any]] = None,
    ) -> CollectionResult:
        """Dispatch to the appropriate sub-collector based on sub_source."""
        start = time.time()
        cursor = dict(cursor_state) if cursor_state else {}

        try:
            if self.sub_source == "budgets":
                result = self._collect_budgets(cursor)
            elif self.sub_source == "supports":
                result = self._collect_supports(cursor)
            elif self.sub_source == "tenders":
                result = self._collect_tenders(cursor)
            else:
                # Shouldn't happen — validated in __init__
                return CollectionResult(
                    source_id=self.get_source_id(),
                    error=f"Unknown sub_source: {self.sub_source}",
                )
        except Exception as exc:
            logger.exception("%s: unexpected error during collection", self.get_source_id())
            return CollectionResult(
                source_id=self.get_source_id(),
                error=str(exc),
                duration_seconds=time.time() - start,
            )

        result.duration_seconds = time.time() - start
        return result

    # ==================================================================
    # BUDGETS — crawl by ministry code, then sub-programs
    # ==================================================================

    def _collect_budgets(self, cursor: Dict[str, Any]) -> CollectionResult:
        """Crawl budget lines by top-level ministry code.

        Cursor state:
            last_code : str   — last fully processed two-digit code (e.g. "05")
            page      : int   — current page within a code (for sub-programs)
        """
        last_code = cursor.get("last_code", "")
        page = cursor.get("page", 0)
        items_new = 0
        items_updated = 0
        items_skipped = 0

        # Determine starting code index
        start_idx = 0
        if last_code:
            try:
                start_idx = int(last_code) + (1 if page == 0 else 0)
            except ValueError:
                start_idx = 0

        current_code = last_code or ""
        current_page = page

        for code_int in MINISTRY_CODE_RANGE:
            if code_int < start_idx:
                continue

            code = f"{code_int:02d}"
            current_code = code

            # Resume from saved page when re-entering the same code
            start_page = current_page if code == last_code else 0
            current_page = start_page

            pages_fetched = 0
            while pages_fetched < MAX_PAGES_PER_RUN:
                query = f"SELECT * FROM budget WHERE code LIKE '{code}%'"
                data = self.fetch_json(
                    QUERY_URL,
                    params={"query": query, "num_rows": DEFAULT_PAGE_SIZE},
                )

                if data is None:
                    logger.warning("%s: failed to fetch code %s", self.get_source_id(), code)
                    break

                rows = data.get("rows", data.get("result", []))
                if not rows:
                    break

                for row in rows:
                    new, updated = self._store_budget_row(row)
                    items_new += new
                    items_updated += updated

                # The query API doesn't support offset natively, so we
                # treat each code as a single batch and move on.
                break

            current_page = 0  # reset for next code

        return CollectionResult(
            source_id=self.get_source_id(),
            items_new=items_new,
            items_updated=items_updated,
            items_skipped=items_skipped,
            new_cursor={"last_code": current_code, "page": 0},
        )

    def _store_budget_row(self, row: Dict[str, Any]) -> tuple[int, int]:
        """Store a single budget row as a graph node.

        Returns (new_count, updated_count) — each is 0 or 1.
        """
        budget_code = str(row.get("code", "")).strip()
        if not budget_code:
            return 0, 0

        title = row.get("title", row.get("name", ""))
        year = _safe_int(row.get("year"))
        node_id = f"budget:{budget_code}:{year}" if year else f"budget:{budget_code}"

        node = {
            "id": node_id,
            "label": "BudgetLine",
            "attributes": {
                "budget_code": budget_code,
                "ministry": _extract_ministry(budget_code, title),
                "program": title,
                "year": year,
                "net_allocated": _safe_float(row.get("net_allocated")),
                "net_revised": _safe_float(row.get("net_revised")),
                "net_used": _safe_float(row.get("net_used")),
            },
            "facts": [f"Budget line {budget_code}: {title}"],
            "source": self.get_source_id(),
        }

        # Determine if this is new or updated by checking graph
        is_new = True
        if self.graph_storage is not None:
            existing = self.graph_storage.get_node(node_id)
            is_new = existing is None

        self.upsert_node(node)

        # Create hierarchy edge: parent code → this code
        # Only if parent node already exists (avoid missing-node errors)
        parent_code = _parent_budget_code(budget_code)
        if parent_code and self.graph_storage is not None:
            parent_year_suffix = f":{year}" if year else ""
            parent_id = f"budget:{parent_code}{parent_year_suffix}"
            parent_exists = self.graph_storage.get_node(parent_id)
            if parent_exists:
                try:
                    self.upsert_edge({
                        "source_id": parent_id,
                        "target_id": node_id,
                        "relation": "BUDGET_UNDER",
                        "attributes": {"year": year},
                        "source": self.get_source_id(),
                    })
                except Exception as e:
                    logger.debug("Skipping budget edge %s -> %s: %s", parent_id, node_id, e)

        return (1, 0) if is_new else (0, 1)

    # ==================================================================
    # SUPPORTS — paginated search for government grants/subsidies
    # ==================================================================

    def _collect_supports(self, cursor: Dict[str, Any]) -> CollectionResult:
        """Collect government supports/grants via SQL query API.

        Cursor state:
            offset : int — row offset for pagination
        """
        offset = cursor.get("offset", 0)
        items_new = 0
        items_updated = 0
        items_skipped = 0
        pages_fetched = 0

        while pages_fetched < MAX_PAGES_PER_RUN:
            query = (
                f"SELECT * FROM raw_supports "
                f"LIMIT {DEFAULT_PAGE_SIZE} OFFSET {offset}"
            )
            data = self.fetch_json(
                QUERY_URL,
                params={"query": query, "num_rows": DEFAULT_PAGE_SIZE},
            )

            if data is None or not data.get("success"):
                logger.warning(
                    "%s: failed to fetch supports at offset %d", self.get_source_id(), offset,
                )
                break

            rows = data.get("rows", [])
            if not rows:
                logger.info("%s: no more supports at offset %d", self.get_source_id(), offset)
                break

            for item in rows:
                new, updated = self._store_support(item)
                items_new += new
                items_updated += updated

            offset += len(rows)
            pages_fetched += 1

            if len(rows) < DEFAULT_PAGE_SIZE:
                break

        return CollectionResult(
            source_id=self.get_source_id(),
            items_new=items_new,
            items_updated=items_updated,
            items_skipped=items_skipped,
            new_cursor={"offset": offset},
        )

    def _store_support(self, item: Dict[str, Any]) -> tuple[int, int]:
        """Store a support/grant item as a graph node."""
        source = item.get("source", item)
        if isinstance(source, dict):
            item = source

        recipient = item.get("entity_name", item.get("recipient", ""))
        budget_code = str(item.get("budget_code", "")).strip()
        year = _safe_int(item.get("year_paid", item.get("year")))
        amount_approved = _safe_float(item.get("amount_approved"))
        amount_paid = _safe_float(item.get("amount_paid"))

        support_id = _make_id(
            "support", recipient, budget_code, str(year),
        )
        node_id = f"support:{support_id}"

        node = {
            "id": node_id,
            "label": "BudgetSupport",
            "attributes": {
                "recipient_name": recipient,
                "ministry": item.get("supporting_ministry", ""),
                "budget_code": budget_code,
                "purpose": item.get("support_title", ""),
                "amount_approved": amount_approved,
                "amount_paid": amount_paid,
                "year": year,
            },
            "facts": [
                f"Support to {recipient}: {amount_paid:,.0f} NIS"
                if amount_paid
                else f"Support to {recipient}"
            ],
            "source": self.get_source_id(),
        }

        is_new = True
        if self.graph_storage is not None:
            existing = self.graph_storage.get_node(node_id)
            is_new = existing is None

        self.upsert_node(node)
        return (1, 0) if is_new else (0, 1)

    # ==================================================================
    # TENDERS — paginated search for government tenders
    # ==================================================================

    def _collect_tenders(self, cursor: Dict[str, Any]) -> CollectionResult:
        """Collect government tenders via SQL query API.

        Cursor state:
            offset : int — row offset for pagination
        """
        offset = cursor.get("offset", 0)
        items_new = 0
        items_updated = 0
        items_skipped = 0
        pages_fetched = 0

        while pages_fetched < MAX_PAGES_PER_RUN:
            query = (
                f"SELECT * FROM contract_spending "
                f"LIMIT {DEFAULT_PAGE_SIZE} OFFSET {offset}"
            )
            data = self.fetch_json(
                QUERY_URL,
                params={"query": query, "num_rows": DEFAULT_PAGE_SIZE},
            )

            if data is None or not data.get("success"):
                logger.warning(
                    "%s: failed to fetch tenders at offset %d", self.get_source_id(), offset,
                )
                break

            rows = data.get("rows", [])
            if not rows:
                logger.info("%s: no more tenders at offset %d", self.get_source_id(), offset)
                break

            for item in rows:
                new, updated = self._store_tender(item)
                items_new += new
                items_updated += updated

            offset += len(rows)
            pages_fetched += 1

            if len(rows) < DEFAULT_PAGE_SIZE:
                break

        return CollectionResult(
            source_id=self.get_source_id(),
            items_new=items_new,
            items_updated=items_updated,
            items_skipped=items_skipped,
            new_cursor={"offset": offset},
        )

    def _store_tender(self, item: Dict[str, Any]) -> tuple[int, int]:
        """Store a contract_spending item as a graph node."""
        source = item.get("source", item)
        if isinstance(source, dict):
            item = source

        description = item.get("purpose", item.get("explanation", ""))
        ministry = item.get("publisher_name", item.get("publisher", ""))
        amount = _safe_float(item.get("volume", item.get("executed", item.get("amount_contracts"))))
        year = _safe_int(item.get("min_year", 0)) or (_safe_int(str(item.get("order_date", ""))[:4]) if item.get("order_date") else 0)
        status = item.get("purchase_method", "")
        tender_id_raw = item.get("order_id", item.get("tender_key", ""))

        tender_id = _make_id("tender", str(tender_id_raw), description[:60])
        node_id = f"tender:{tender_id}"

        node = {
            "id": node_id,
            "label": "BudgetTender",
            "attributes": {
                "description": description,
                "ministry": ministry,
                "amount": amount,
                "year": year,
                "status": str(status),
            },
            "facts": [f"Tender: {description[:120]}"],
            "source": self.get_source_id(),
        }

        is_new = True
        if self.graph_storage is not None:
            existing = self.graph_storage.get_node(node_id)
            is_new = existing is None

        self.upsert_node(node)
        return (1, 0) if is_new else (0, 1)


# ======================================================================
# Module-level helpers
# ======================================================================

def _extract_search_results(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract result list from obudget search response.

    The search API wraps results in various structures depending on
    the endpoint.  We normalise them here.
    """
    if "search_results" in data:
        results = data["search_results"]
        if isinstance(results, list):
            return results
        if isinstance(results, dict):
            return results.get("results", [])

    if "results" in data:
        return data["results"]

    # Sometimes the response is a flat list
    if isinstance(data, list):
        return data

    return []


def _parent_budget_code(code: str) -> Optional[str]:
    """Return the parent budget code by stripping the last two digits.

    Israeli budget codes are hierarchical:
      00       → ministry
      0012     → program within ministry
      001234   → sub-program
    """
    code = code.strip()
    if len(code) <= 2:
        return None
    return code[:-2]


def _extract_ministry(code: str, title: str) -> str:
    """Best-effort extraction of ministry name from budget code / title."""
    # Top-level (2-digit) codes usually ARE the ministry
    if len(code.strip()) == 2:
        return title
    # Otherwise return empty — will be enriched later
    return ""


def _safe_float(val: Any) -> float:
    """Coerce a value to float, returning 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val: Any) -> int:
    """Coerce a value to int, returning 0 on failure."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _make_id(*parts: str) -> str:
    """Create a short deterministic ID from multiple string parts."""
    raw = ":".join(p for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
