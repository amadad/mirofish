"""Knesset-specific graph query helper.

Wraps GraphStorage with convenience methods for querying MKs, factions,
bills, and relationships.  All methods return plain dicts ready for
JSON serialization.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..graph_storage import GraphStorage

from ...utils.logger import get_logger

logger = get_logger("mirofish.knesset_graph")


class KnessetGraph:
    """High-level Knesset-domain queries on top of GraphStorage."""

    def __init__(self, graph_storage: GraphStorage) -> None:
        self.storage = graph_storage

    # ------------------------------------------------------------------
    # MK queries
    # ------------------------------------------------------------------

    def get_all_mks(self, current_only: bool = True) -> List[Dict[str, Any]]:
        """Return all MK nodes, optionally filtered to current members only."""
        nodes = self.storage.list_nodes(label="MK")
        if current_only:
            nodes = [
                n for n in nodes
                if self._attr(n, "is_current_mk", True)
            ]
        return nodes

    def get_mk(self, mk_id: str) -> Optional[Dict[str, Any]]:
        """Get a single MK node by ID."""
        return self.storage.get_node(mk_id)

    def get_faction_members(self, faction_name: str) -> List[Dict[str, Any]]:
        """Get all MKs belonging to *faction_name*.

        Checks both MEMBER_OF edges and the ``faction`` attribute on MK nodes.
        """
        members: List[Dict[str, Any]] = []
        seen_ids: set = set()

        # Strategy 1: MEMBER_OF edges targeting a Faction node
        faction_node = self.storage.get_node_by_name(faction_name)
        if faction_node:
            edges = self.storage.get_edges(
                target_id=faction_node["id"], relation="MEMBER_OF"
            )
            for edge in edges:
                mk = self.storage.get_node(edge["source_id"])
                if mk and mk["id"] not in seen_ids:
                    members.append(mk)
                    seen_ids.add(mk["id"])

        # Strategy 2: MK nodes with matching faction attribute
        for mk in self.storage.list_nodes(label="MK"):
            attrs = mk.get("attributes", {}) or {}
            if (
                attrs.get("faction") == faction_name
                and mk["id"] not in seen_ids
            ):
                members.append(mk)
                seen_ids.add(mk["id"])

        return members

    # ------------------------------------------------------------------
    # Faction / coalition queries
    # ------------------------------------------------------------------

    def get_coalition_factions(self) -> List[str]:
        """Return names of all coalition factions.

        Looks for Faction nodes that have a COALITION edge or a
        ``coalition_member`` attribute set to true.
        """
        return self._get_factions_by_alignment(is_coalition=True)

    def get_opposition_factions(self) -> List[str]:
        """Return names of all opposition factions."""
        return self._get_factions_by_alignment(is_coalition=False)

    def _get_factions_by_alignment(self, is_coalition: bool) -> List[str]:
        names: List[str] = []
        for node in self.storage.list_nodes(label="Faction"):
            attrs = node.get("attributes", {}) or {}
            cm = attrs.get("coalition_member")
            if cm is None:
                # Check edges — FACTION_COALITION relation means coalition
                edges = self.storage.get_edges(
                    source_id=node["id"], relation="FACTION_COALITION"
                )
                in_coalition = len(edges) > 0
            else:
                in_coalition = str(cm).lower() in ("true", "1", "yes")

            if in_coalition == is_coalition:
                names.append(node.get("name", node["id"]))
        return names

    # ------------------------------------------------------------------
    # MK relationship queries
    # ------------------------------------------------------------------

    def get_mk_relationships(self, mk_id: str) -> Dict[str, Any]:
        """Return all edges for an MK grouped by type.

        Returns:
            {
                "faction": [edge, ...],
                "votes": [edge, ...],
                "committees": [edge, ...],
                "alliances": [edge, ...],
                "other": [edge, ...],
            }
        """
        outgoing = self.storage.get_edges(source_id=mk_id)
        incoming = self.storage.get_edges(target_id=mk_id)
        all_edges = outgoing + incoming

        grouped: Dict[str, List[Dict[str, Any]]] = {
            "faction": [],
            "votes": [],
            "committees": [],
            "alliances": [],
            "other": [],
        }

        relation_map = {
            "MEMBER_OF": "faction",
            "FACTION_COALITION": "faction",
            "VOTED_FOR": "votes",
            "VOTED_AGAINST": "votes",
            "ABSTAINED": "votes",
            "COMMITTEE_MEMBER": "committees",
            "COMMITTEE_CHAIR": "committees",
            "ALLIED_WITH": "alliances",
            "LOBBIED": "alliances",
        }

        for edge in all_edges:
            rel = edge.get("relation", "")
            bucket = relation_map.get(rel, "other")
            grouped[bucket].append(edge)

        return grouped

    # ------------------------------------------------------------------
    # Bill queries
    # ------------------------------------------------------------------

    def get_bills(
        self,
        search: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query bill nodes with optional text search and status filter."""
        nodes = self.storage.list_nodes(label="Bill")

        if status:
            nodes = [
                n for n in nodes
                if self._attr(n, "status") == status
            ]

        if search:
            search_lower = search.lower()
            nodes = [
                n for n in nodes
                if search_lower in (n.get("name", "") or "").lower()
                or search_lower in (n.get("summary", "") or "").lower()
                or search_lower in str(self._attr(n, "title_he", "")).lower()
            ]

        return nodes[:limit]

    def get_bill(self, bill_id: str) -> Optional[Dict[str, Any]]:
        """Get a single bill node with its related edges."""
        node = self.storage.get_node(bill_id)
        if not node:
            return None
        edges = (
            self.storage.get_edges(source_id=bill_id)
            + self.storage.get_edges(target_id=bill_id)
        )
        return {**node, "edges": edges}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_mks_by_name(self, query: str) -> List[Dict[str, Any]]:
        """Fuzzy search MKs by Hebrew name.

        Uses substring matching and falls back to token overlap for
        partial matches.
        """
        query_clean = query.strip()
        if not query_clean:
            return []

        all_mks = self.storage.list_nodes(label="MK")
        exact: List[Dict[str, Any]] = []
        partial: List[Dict[str, Any]] = []

        query_tokens = set(query_clean.split())

        for mk in all_mks:
            name = mk.get("name", "")
            if query_clean in name or name in query_clean:
                exact.append(mk)
            elif query_tokens & set(name.split()):
                partial.append(mk)

        return exact + partial

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, int]:
        """Return counts of MKs, factions, bills, and edges."""
        mks = self.storage.list_nodes(label="MK")
        factions = self.storage.list_nodes(label="Faction")
        bills = self.storage.list_nodes(label="Bill")
        # Total edges: count from all nodes (approximate — may double-count)
        edge_count = 0
        for node in mks + factions + bills:
            edge_count += len(self.storage.get_edges(source_id=node["id"]))

        return {
            "mks_count": len(mks),
            "factions_count": len(factions),
            "bills_count": len(bills),
            "edges_count": edge_count,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _attr(
        node: Dict[str, Any], key: str, default: Any = None
    ) -> Any:
        """Read a value from node['attributes'][key] with fallback."""
        attrs = node.get("attributes")
        if isinstance(attrs, dict):
            return attrs.get(key, default)
        return default
