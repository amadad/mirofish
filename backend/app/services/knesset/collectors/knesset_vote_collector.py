"""Knesset Vote collector via OData API.

Fetches plenary vote events and per-faction vote statistics.
Creates VOTED_FOR / VOTED_AGAINST edges between factions and bills,
and attaches aggregate voting data to existing Bill nodes.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.votes")

# Maps Knesset ResultID values to human-readable outcomes
RESULT_MAP = {
    1: "accepted",
    2: "rejected",
    3: "removed",
    4: "combined",
}


class KnessetVoteCollector(BaseKnessetCollector):
    """Collects voting records from the Knesset OData API.

    Entities used:
        KNS_VoteMain      — vote events (linked to bills via ItemID)
        KNS_VoteStatistic — per-faction tallies for each vote event
    """

    SOURCE_ID = "knesset:odata:votes"

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
        last_vote_id = cursor_state.get("last_vote_id", 0)

        try:
            # 1. Fetch vote events ------------------------------------
            votes = self._fetch_votes(last_vote_id)
            if not votes:
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    new_cursor=cursor_state,
                    duration_seconds=time.time() - start,
                )

            vote_ids = [v.get("VoteID", 0) for v in votes]
            max_vote_id = max(vote_ids) if vote_ids else last_vote_id

            # 2. Fetch vote statistics for those votes -----------------
            stats = self._fetch_vote_statistics(vote_ids)
            stats_by_vote = self._group_stats_by_vote(stats)

            # 3. Process each vote event -------------------------------
            new_count = 0
            updated_count = 0
            edges_created = 0

            for vote in votes:
                vid = vote.get("VoteID", 0)
                vote_stats = stats_by_vote.get(vid, [])

                # Attach vote data to existing Bill node if possible
                was_new = self._attach_vote_to_bill(vote, vote_stats)
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Create faction-level voting edges
                edges_created += self._create_voting_edges(vote, vote_stats)

            new_cursor = {"last_vote_id": max_vote_id}

            logger.info(
                "%s: processed %d votes (%d new, %d updated), %d edges",
                self.get_source_id(),
                len(votes),
                new_count,
                updated_count,
                edges_created,
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

    def _fetch_votes(self, last_vote_id: int) -> List[Dict[str, Any]]:
        """Fetch plenary vote events incrementally.

        Note: KNS_VoteMain is not available in all OData API versions.
        We try multiple entity names as fallback.
        """
        for entity in ("KNS_VoteMain", "KNS_Vote"):
            odata_filter = f"VoteID gt {last_vote_id}"
            votes = self.fetch_odata_all(
                entity,
                params={
                    "$filter": odata_filter,
                    "$orderby": "VoteID asc",
                },
                page_size=200,
                max_pages=200,
            )
            if votes:
                logger.info(
                    "%s: fetched %d vote events from %s (after VoteID=%d)",
                    self.get_source_id(), len(votes), entity, last_vote_id,
                )
                return votes

        # Fallback: try Hasadna GCS vote data
        votes = self._fetch_votes_from_hasadna(last_vote_id)
        logger.info(
            "%s: fetched %d vote events (after VoteID=%d)",
            self.get_source_id(), len(votes), last_vote_id,
        )
        return votes

    def _fetch_votes_from_hasadna(self, last_vote_id: int) -> List[Dict[str, Any]]:
        """Fallback: fetch vote data from Hasadna GCS pipeline."""
        csv_url = "https://storage.googleapis.com/knesset-data-pipelines/data/votes/all.csv"
        text = self.fetch_text(csv_url)
        if not text:
            return []

        import csv
        import io
        reader = csv.DictReader(io.StringIO(text))
        votes = []
        for row in reader:
            try:
                vid = int(row.get("VoteID", row.get("vote_id", 0)))
                if vid > last_vote_id:
                    votes.append({
                        "VoteID": vid,
                        "ItemID": row.get("ItemID", row.get("item_id", "")),
                        "TypeDesc": row.get("TypeDesc", row.get("type_desc", "")),
                        "Date": row.get("Date", row.get("date", "")),
                        "AcceptedText": row.get("AcceptedText", ""),
                    })
            except (ValueError, TypeError):
                continue
        return votes[:5000]  # Cap for safety

    def _fetch_vote_statistics(
        self, vote_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """Fetch KNS_VoteStatistic rows for a set of vote IDs."""
        all_stats: List[Dict[str, Any]] = []
        batch_size = 50
        for i in range(0, len(vote_ids), batch_size):
            batch = vote_ids[i : i + batch_size]
            filter_parts = " or ".join(f"VoteID eq {vid}" for vid in batch)
            rows = self.fetch_odata_all(
                "KNS_VoteStatistic",
                params={"$filter": filter_parts},
                page_size=500,
            )
            all_stats.extend(rows)
        logger.info(
            "%s: fetched %d vote statistic records",
            self.get_source_id(),
            len(all_stats),
        )
        return all_stats

    # ------------------------------------------------------------------
    # Data transformation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_stats_by_vote(
        stats: List[Dict[str, Any]],
    ) -> Dict[int, List[Dict[str, Any]]]:
        grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in stats:
            grouped[row.get("VoteID", 0)].append(row)
        return dict(grouped)

    @staticmethod
    def _compute_aggregates(
        vote_stats: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Sum up for/against/abstain across all factions for a single vote."""
        total_for = 0
        total_against = 0
        total_abstain = 0
        for stat in vote_stats:
            total_for += stat.get("ForVotes", 0) or 0
            total_against += stat.get("AgainstVotes", 0) or 0
            total_abstain += stat.get("AbstainVotes", 0) or 0
        return {
            "total_for": total_for,
            "total_against": total_against,
            "total_abstain": total_abstain,
        }

    def _resolve_item_to_bill(self, item_id: Optional[int]) -> Optional[str]:
        """Attempt to resolve a vote ItemID to a bill node ID.

        The Knesset OData model links votes to agenda items via ItemID.
        We attempt a best-effort lookup — if no bill is found, return None.
        """
        if not item_id:
            return None
        # Try to find a bill node that matches this item ID
        # In the Knesset OData model, ItemID can correspond to a BillID
        # via the KNS_ItemBill linking table. For simplicity, we check
        # if a bill node already exists with this ID.
        bill_node_id = f"bill_{item_id}"
        if self.graph_storage and self.graph_storage.get_node(bill_node_id):
            return bill_node_id
        return None

    # ------------------------------------------------------------------
    # Node updates and edge creation
    # ------------------------------------------------------------------

    def _attach_vote_to_bill(
        self,
        vote: Dict[str, Any],
        vote_stats: List[Dict[str, Any]],
    ) -> bool:
        """Attach aggregate voting data to the related Bill node.

        Returns True if a bill was found and updated (treated as 'new' data),
        False otherwise.
        """
        vid = vote.get("VoteID", 0)
        item_id = vote.get("ItemID")
        bill_node_id = self._resolve_item_to_bill(item_id)

        if not bill_node_id or not self.graph_storage:
            return False

        aggregates = self._compute_aggregates(vote_stats)
        vote_date = self.parse_odata_date(vote.get("Date"))
        result_id = vote.get("ResultID", 0)
        result_text = RESULT_MAP.get(result_id, f"unknown_{result_id}")
        accepted_text = vote.get("AcceptedText", "")
        reject_text = vote.get("RejectText", "")

        vote_record = {
            "vote_id": vid,
            "date": vote_date,
            "type_desc": vote.get("TypeDesc", ""),
            "result": result_text,
            "accepted_text": accepted_text,
            "reject_text": reject_text,
            **aggregates,
            "faction_breakdown": self._build_faction_breakdown(vote_stats),
        }

        # Update the bill node's attributes with this vote record
        existing = self.graph_storage.get_node(bill_node_id)
        if existing:
            attrs = existing.get("attributes", {})
            votes_list: List[Dict[str, Any]] = attrs.get("votes", [])
            # Avoid duplicates
            existing_vote_ids = {v.get("vote_id") for v in votes_list}
            if vid not in existing_vote_ids:
                votes_list.append(vote_record)
                attrs["votes"] = votes_list
                attrs["last_vote_result"] = result_text
                self.graph_storage.update_node(bill_node_id, {"attributes": attrs})
                return True

        return False

    @staticmethod
    def _build_faction_breakdown(
        vote_stats: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build a per-faction voting breakdown for a single vote."""
        breakdown: List[Dict[str, Any]] = []
        for stat in vote_stats:
            fid = stat.get("FactionID")
            if not fid:
                continue
            breakdown.append({
                "faction_id": fid,
                "faction_size": stat.get("FactionSize", 0),
                "for": stat.get("ForVotes", 0) or 0,
                "against": stat.get("AgainstVotes", 0) or 0,
                "abstain": stat.get("AbstainVotes", 0) or 0,
            })
        return breakdown

    def _create_voting_edges(
        self,
        vote: Dict[str, Any],
        vote_stats: List[Dict[str, Any]],
    ) -> int:
        """Create VOTED_FOR / VOTED_AGAINST edges between factions and bills.

        Returns the number of edges created.
        """
        item_id = vote.get("ItemID")
        bill_node_id = self._resolve_item_to_bill(item_id)
        if not bill_node_id:
            return 0

        vid = vote.get("VoteID", 0)
        vote_date = self.parse_odata_date(vote.get("Date"))
        edges_created = 0

        for stat in vote_stats:
            fid = stat.get("FactionID")
            if not fid:
                continue

            faction_node_id = f"faction_{fid}"
            for_votes = stat.get("ForVotes", 0) or 0
            against_votes = stat.get("AgainstVotes", 0) or 0

            # Determine the dominant faction stance
            if for_votes > against_votes:
                relation = "VOTED_FOR"
            elif against_votes > for_votes:
                relation = "VOTED_AGAINST"
            else:
                # Tie or no votes — skip edge creation
                continue

            edge = {
                "source_id": faction_node_id,
                "target_id": bill_node_id,
                "relation": relation,
                "attributes": {
                    "vote_id": vid,
                    "date": vote_date,
                    "for_votes": for_votes,
                    "against_votes": against_votes,
                    "abstain_votes": stat.get("AbstainVotes", 0) or 0,
                    "faction_size": stat.get("FactionSize", 0),
                },
            }
            self.upsert_edge(edge)
            edges_created += 1

        return edges_created
