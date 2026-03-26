"""Open Knesset (oknesset.org) data collector.

Collects processed parliamentary data from the Open Knesset project,
including MK voting analysis, bill tracking, and faction activity.
Falls back to Hasadna GitHub data if the API is unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.oknesset")

OKNESSET_API_BASE = "https://oknesset.org/api"
OKNESSET_MEMBERS_URL = f"{OKNESSET_API_BASE}/members"
OKNESSET_BILLS_URL = f"{OKNESSET_API_BASE}/bills"
OKNESSET_VOTES_URL = f"{OKNESSET_API_BASE}/votes"

# Fallback: Hasadna GitHub raw data
HASADNA_GH_BASE = (
    "https://raw.githubusercontent.com/hasadna/open-knesset-data/master"
)


class OKnessetCollector(BaseKnessetCollector):
    """Collects processed data from the Open Knesset project.

    Primary source: https://oknesset.org/api/
    Fallback: Hasadna GitHub data pipelines.

    Data is used as enrichment on existing MK and Bill nodes rather
    than creating new entity types.
    """

    SOURCE_ID = "oknesset:api"
    RATE_LIMIT_SECONDS = 1.0  # Be polite to community project

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
        page = cursor_state.get("page", 1)
        source = cursor_state.get("source", "api")  # "api" or "github"

        try:
            new_count = 0
            updated_count = 0

            if source == "api":
                ok = self._check_api_available()
                if not ok:
                    logger.warning(
                        "%s: API unavailable, falling back to GitHub data",
                        self.get_source_id(),
                    )
                    source = "github"

            if source == "api":
                # Collect from oknesset API
                mk_count, mk_page = self._collect_member_data(page)
                bill_count, bill_page = self._collect_bill_data(page)
                vote_count, vote_page = self._collect_vote_data(page)

                updated_count = mk_count + bill_count + vote_count
                next_page = max(mk_page, bill_page, vote_page)

                new_cursor = {"page": next_page, "source": "api"}
            else:
                # Fallback: collect from Hasadna GitHub
                gh_count = self._collect_from_github()
                updated_count = gh_count
                new_cursor = {"page": 1, "source": "github"}

            logger.info(
                "%s: enriched %d items from %s",
                self.get_source_id(),
                updated_count,
                source,
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
    # API availability check
    # ------------------------------------------------------------------

    def _check_api_available(self) -> bool:
        """Probe the oknesset API to see if it responds."""
        data = self.fetch_json(OKNESSET_API_BASE, params={"format": "json"})
        return data is not None

    # ------------------------------------------------------------------
    # API-based collection
    # ------------------------------------------------------------------

    def _collect_member_data(self, page: int) -> tuple[int, int]:
        """Fetch MK voting analysis and enrich existing MK nodes.

        Returns (items_updated, next_page).
        """
        count = 0
        data = self.fetch_json(
            OKNESSET_MEMBERS_URL,
            params={"page": str(page), "format": "json"},
        )
        if not data:
            return 0, page

        members = data.get("results", data) if isinstance(data, dict) else data
        if not isinstance(members, list):
            members = [members] if members else []

        for member in members:
            mk_id = member.get("id") or member.get("mk_id")
            if not mk_id:
                continue

            node_id = f"mk_{mk_id}"
            enrichment = {
                "id": node_id,
                "label": "MK",
                "attributes": {},
                "facts": [],
            }

            # Voting analysis
            if "voting_statistics" in member:
                enrichment["attributes"]["oknesset_voting_stats"] = (
                    member["voting_statistics"]
                )
            if "agendas" in member:
                enrichment["attributes"]["oknesset_agendas"] = member["agendas"]
            if "party_discipline" in member:
                enrichment["attributes"]["party_discipline"] = (
                    member["party_discipline"]
                )
            if "bills_stats_proposed" in member:
                enrichment["attributes"]["oknesset_bills_proposed"] = (
                    member["bills_stats_proposed"]
                )

            if enrichment["attributes"]:
                self.upsert_node(enrichment)
                count += 1

        # Determine next page
        next_page = page + 1 if len(members) >= 20 else page
        return count, next_page

    def _collect_bill_data(self, page: int) -> tuple[int, int]:
        """Fetch bill tracking data and enrich existing Bill nodes.

        Returns (items_updated, next_page).
        """
        count = 0
        data = self.fetch_json(
            OKNESSET_BILLS_URL,
            params={"page": str(page), "format": "json"},
        )
        if not data:
            return 0, page

        bills = data.get("results", data) if isinstance(data, dict) else data
        if not isinstance(bills, list):
            bills = [bills] if bills else []

        for bill in bills:
            bill_id = bill.get("id") or bill.get("bill_id")
            if not bill_id:
                continue

            node_id = f"bill_{bill_id}"
            enrichment = {
                "id": node_id,
                "label": "Bill",
                "attributes": {
                    "oknesset_stage": bill.get("stage", ""),
                    "oknesset_stage_text": bill.get("stage_text", ""),
                },
                "facts": [],
            }

            if "proposers" in bill:
                enrichment["attributes"]["oknesset_proposers"] = bill["proposers"]
            if "popular_name" in bill:
                enrichment["attributes"]["popular_name"] = bill["popular_name"]

            if enrichment["attributes"]:
                self.upsert_node(enrichment)
                count += 1

        next_page = page + 1 if len(bills) >= 20 else page
        return count, next_page

    def _collect_vote_data(self, page: int) -> tuple[int, int]:
        """Fetch vote data and enrich existing Bill/MK nodes.

        Returns (items_updated, next_page).
        """
        count = 0
        data = self.fetch_json(
            OKNESSET_VOTES_URL,
            params={"page": str(page), "format": "json"},
        )
        if not data:
            return 0, page

        votes = data.get("results", data) if isinstance(data, dict) else data
        if not isinstance(votes, list):
            votes = [votes] if votes else []

        for vote in votes:
            vote_id = vote.get("id")
            if not vote_id:
                continue

            # If vote is linked to a bill, enrich that bill
            bill_id = vote.get("bill_id")
            if bill_id:
                node_id = f"bill_{bill_id}"
                enrichment = {
                    "id": node_id,
                    "label": "Bill",
                    "attributes": {},
                    "facts": [],
                }
                vote_summary = {
                    "vote_id": vote_id,
                    "for_votes": vote.get("for_votes_count", 0),
                    "against_votes": vote.get("against_votes_count", 0),
                    "abstain_votes": vote.get("abstain_votes_count", 0),
                    "date": vote.get("time", ""),
                }
                enrichment["attributes"]["oknesset_vote_summary"] = vote_summary
                self.upsert_node(enrichment)
                count += 1

        next_page = page + 1 if len(votes) >= 20 else page
        return count, next_page

    # ------------------------------------------------------------------
    # GitHub fallback
    # ------------------------------------------------------------------

    def _collect_from_github(self) -> int:
        """Collect basic MK data from Hasadna GitHub as fallback.

        Returns items_updated count.
        """
        count = 0
        members_url = f"{HASADNA_GH_BASE}/members/index.json"
        data = self.fetch_json(members_url)
        if not data:
            logger.warning(
                "%s: GitHub fallback also unavailable", self.get_source_id(),
            )
            return 0

        members = data if isinstance(data, list) else data.get("members", [])

        for member in members:
            mk_id = member.get("id") or member.get("mk_id")
            if not mk_id:
                continue

            node_id = f"mk_{mk_id}"
            enrichment = {
                "id": node_id,
                "label": "MK",
                "attributes": {
                    "oknesset_github_data": True,
                },
                "facts": [],
            }

            if "party" in member:
                enrichment["attributes"]["oknesset_party"] = member["party"]
            if "role" in member:
                enrichment["attributes"]["oknesset_role"] = member["role"]

            self.upsert_node(enrichment)
            count += 1

        return count
