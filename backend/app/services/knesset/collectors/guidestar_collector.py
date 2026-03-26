"""GuideStar Israel NGO/association data collector.

Collects information about non-profit organizations from GuideStar
Israel (guidestar.org.il), focusing on organizations that receive
government support and their financial data.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.guidestar")

GUIDESTAR_API_BASE = "https://www.guidestar.org.il/api"
GUIDESTAR_SEARCH_URL = f"{GUIDESTAR_API_BASE}/organizations"

# Fallback: use the public search page scraping approach
GUIDESTAR_PUBLIC_SEARCH = "https://www.guidestar.org.il/search"

# Categories of interest for parliamentary analysis
NGO_CATEGORIES = [
    "education",
    "religion",
    "culture",
    "welfare",
    "health",
    "settlements",
    "security",
]

# Page size for API requests
PAGE_SIZE = 20


class GuideStarCollector(BaseKnessetCollector):
    """Collects NGO/association data from GuideStar Israel.

    Creates Organization nodes (label="Organization", subtype="ngo")
    and RECEIVES_SUPPORT edges to BudgetSupport nodes when government
    funding data is available.

    Note: GuideStar may require API registration. The collector
    degrades gracefully if access is unavailable.
    """

    SOURCE_ID = "guidestar:ngos"
    RATE_LIMIT_SECONDS = 1.0
    REQUEST_TIMEOUT = 30

    def __init__(
        self,
        graph_storage=None,
        pinecone_service=None,
        api_key: Optional[str] = None,
    ):
        super().__init__(graph_storage, pinecone_service)
        self.api_key = api_key
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

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
        category_index = cursor_state.get("category_index", 0)
        page = cursor_state.get("page", 1)

        if category_index >= len(NGO_CATEGORIES):
            # All categories processed — reset
            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=0,
                items_updated=0,
                new_cursor={"category_index": 0, "page": 1},
                duration_seconds=time.time() - start,
            )

        try:
            category = NGO_CATEGORIES[category_index]
            new_count = 0
            updated_count = 0

            # Try API first, fall back to public data
            orgs = self._fetch_organizations(category, page)
            if orgs is None:
                logger.warning(
                    "%s: API unavailable for category '%s'",
                    self.get_source_id(),
                    category,
                )
                # Move to next category
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    items_skipped=1,
                    new_cursor={
                        "category_index": category_index + 1,
                        "page": 1,
                    },
                    duration_seconds=time.time() - start,
                )

            for org in orgs:
                was_new = self._upsert_organization_node(org, category)
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Create budget support edges if financial data exists
                self._create_support_edges(org)

            # Pagination: advance page or move to next category
            if len(orgs) >= PAGE_SIZE:
                new_cursor = {
                    "category_index": category_index,
                    "page": page + 1,
                }
            else:
                new_cursor = {
                    "category_index": category_index + 1,
                    "page": 1,
                }

            logger.info(
                "%s: category '%s' page %d — %d orgs (%d new, %d updated)",
                self.get_source_id(),
                category,
                page,
                len(orgs),
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
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_organizations(
        self, category: str, page: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch organizations from GuideStar API.

        Returns list of org dicts, or None if API is unavailable.
        """
        data = self.fetch_json(
            GUIDESTAR_SEARCH_URL,
            params={
                "category": category,
                "page": str(page),
                "pageSize": str(PAGE_SIZE),
                "hasGovernmentSupport": "true",
            },
        )
        if data is None:
            return None

        # Handle various response formats
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return (
                data.get("organizations")
                or data.get("results")
                or data.get("data", [])
            )
        return []

    def _fetch_org_details(
        self, org_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch detailed financial data for a single organization."""
        url = f"{GUIDESTAR_SEARCH_URL}/{org_id}"
        return self.fetch_json(url)

    # ------------------------------------------------------------------
    # Node / edge upsert
    # ------------------------------------------------------------------

    def _upsert_organization_node(
        self, org: Dict[str, Any], category: str,
    ) -> bool:
        """Build and upsert an Organization node. Returns True if new."""
        org_id = (
            org.get("id")
            or org.get("regNum")
            or org.get("organization_id", "")
        )
        if not org_id:
            return False

        node_id = f"org_gs_{org_id}"
        name = org.get("name") or org.get("orgName", f"Org {org_id}")

        is_new = (
            self.graph_storage
            and self.graph_storage.get_node(node_id) is None
        )

        node = {
            "id": node_id,
            "name": name,
            "label": "Organization",
            "attributes": {
                "subtype": "ngo",
                "guidestar_id": str(org_id),
                "category": category,
                "registration_number": org.get("regNum", ""),
                "city": org.get("city", ""),
                "status": org.get("status", ""),
                "founded_year": org.get("foundedYear") or org.get("yearFounded"),
                "annual_turnover": org.get("annualTurnover"),
                "has_government_support": org.get("hasGovernmentSupport", False),
                "government_support_amount": org.get("governmentSupportAmount"),
                "num_employees": org.get("numEmployees"),
                "num_volunteers": org.get("numVolunteers"),
                "proper_management": org.get("properManagement", False),
                "section46": org.get("section46", False),
            },
            "facts": [
                f"NGO '{name}' (GuideStar ID={org_id}, category={category})",
            ],
        }
        self.upsert_node(node)

        # Index for semantic search
        search_text = (
            f"Organization: {name}. "
            f"Category: {category}. "
            f"City: {org.get('city', 'unknown')}."
        )
        self.index_in_pinecone(
            text=search_text,
            metadata={"id": node_id, "label": "Organization", "name": name},
            namespace="knesset_organizations",
        )

        return bool(is_new)

    def _create_support_edges(self, org: Dict[str, Any]) -> None:
        """Create RECEIVES_SUPPORT edges for government-funded organizations."""
        org_id = (
            org.get("id")
            or org.get("regNum")
            or org.get("organization_id", "")
        )
        if not org_id:
            return

        support_amount = org.get("governmentSupportAmount")
        if not support_amount:
            return

        node_id = f"org_gs_{org_id}"

        # Get or reference supporting ministries
        ministries = org.get("supportingMinistries", [])
        if not ministries:
            # Create a generic government support edge
            support_node_id = f"budget_support_{org_id}"
            support_node = {
                "id": support_node_id,
                "name": f"Government support for {org.get('name', org_id)}",
                "label": "BudgetSupport",
                "attributes": {
                    "amount": support_amount,
                    "year": org.get("supportYear", ""),
                    "currency": "ILS",
                },
                "facts": [],
            }
            self.upsert_node(support_node)

            edge = {
                "source_id": node_id,
                "target_id": support_node_id,
                "relation": "RECEIVES_SUPPORT",
                "attributes": {
                    "amount": support_amount,
                    "year": org.get("supportYear", ""),
                },
            }
            self.upsert_edge(edge)
        else:
            # Create edges per supporting ministry
            for ministry in ministries:
                ministry_name = (
                    ministry if isinstance(ministry, str)
                    else ministry.get("name", "")
                )
                if not ministry_name:
                    continue

                ministry_node_id = (
                    f"ministry_{ministry_name.replace(' ', '_').lower()[:30]}"
                )
                ministry_node = {
                    "id": ministry_node_id,
                    "name": ministry_name,
                    "label": "Ministry",
                    "attributes": {},
                    "facts": [],
                }
                self.upsert_node(ministry_node)

                amount = (
                    ministry.get("amount", support_amount)
                    if isinstance(ministry, dict)
                    else support_amount
                )
                edge = {
                    "source_id": node_id,
                    "target_id": ministry_node_id,
                    "relation": "RECEIVES_SUPPORT",
                    "attributes": {
                        "amount": amount,
                        "year": org.get("supportYear", ""),
                    },
                }
                self.upsert_edge(edge)
