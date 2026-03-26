"""Budget flow analysis — ministry → program → recipients → connected MKs.

Analyzes government budget data to find:
1. Which MKs are connected to which budget lines
2. Which organizations receive government funding
3. Budget trends over time
4. MK budget interests for simulation
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.knesset.budget_analyzer")


class BudgetAnalyzer:
    """Analyze budget flows and MK connections."""

    def __init__(self, graph_storage=None):
        self.graph_storage = graph_storage

    def get_ministry_budget(self, ministry: str) -> Dict[str, Any]:
        """Get all budget lines for a ministry with hierarchy."""
        if self.graph_storage is None:
            return {"error": "No graph storage"}

        lines: List[Dict[str, Any]] = []
        total_allocated = 0.0
        total_used = 0.0

        for node in self.graph_storage.list_nodes(label="BudgetLine"):
            attrs = node.get("attributes", {})
            if ministry in (attrs.get("ministry", "") or ""):
                allocated = attrs.get("net_allocated", 0) or 0
                used = attrs.get("net_used", 0) or 0
                total_allocated += allocated
                total_used += used
                lines.append({
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "budget_code": attrs.get("budget_code"),
                    "program": attrs.get("program"),
                    "net_allocated": allocated,
                    "net_used": used,
                    "year": attrs.get("year"),
                })

        return {
            "ministry": ministry,
            "total_allocated": total_allocated,
            "total_used": total_used,
            "utilization_pct": round(total_used / total_allocated * 100, 1) if total_allocated else 0,
            "lines": sorted(lines, key=lambda x: -(x.get("net_allocated") or 0)),
        }

    def get_mk_budget_connections(self, mk_id: str) -> Dict[str, Any]:
        """Find budget lines connected to an MK through various paths."""
        if self.graph_storage is None:
            return {"error": "No graph storage"}

        connections: List[Dict[str, Any]] = []

        # Path 1: Bills proposed by MK that reference budget codes
        for edge in self.graph_storage.get_edges(source_id=mk_id, relation="PROPOSED"):
            bill = self.graph_storage.get_node(edge.get("target_id", ""))
            if bill:
                codes = bill.get("attributes", {}).get("related_budget_codes", [])
                for code in codes:
                    connections.append({
                        "path": "bill_sponsorship",
                        "bill_id": bill.get("id"),
                        "bill_name": bill.get("name"),
                        "budget_code": code,
                    })

        # Path 2: Committee membership → budget oversight
        for edge in self.graph_storage.get_edges(source_id=mk_id, relation="SITS_ON"):
            committee = self.graph_storage.get_node(edge.get("target_id", ""))
            if committee and "כספים" in (committee.get("name", "") or ""):
                connections.append({
                    "path": "committee_oversight",
                    "committee_id": committee.get("id"),
                    "committee_name": committee.get("name"),
                    "role": "finance_committee_member",
                })

        # Path 3: Lobby connections to organizations that receive funding
        for edge in self.graph_storage.get_edges(source_id=mk_id, relation="LOBBIED_BY"):
            org = self.graph_storage.get_node(edge.get("target_id", ""))
            if org:
                # Check if this org receives budget support
                supports = self.graph_storage.get_edges(
                    source_id=org.get("id", ""),
                    relation="RECEIVES_SUPPORT",
                )
                for support_edge in supports:
                    connections.append({
                        "path": "lobby_funding",
                        "org_id": org.get("id"),
                        "org_name": org.get("name"),
                        "support_id": support_edge.get("target_id"),
                    })

        return {
            "mk_id": mk_id,
            "budget_connections": connections,
            "total_connections": len(connections),
        }

    def get_top_recipients(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get organizations that receive the most government funding."""
        if self.graph_storage is None:
            return []

        recipient_totals: Dict[str, Dict[str, Any]] = {}

        for node in self.graph_storage.list_nodes(label="BudgetSupport"):
            attrs = node.get("attributes", {})
            recipient = attrs.get("recipient_name", "")
            if not recipient:
                continue

            if recipient not in recipient_totals:
                recipient_totals[recipient] = {
                    "recipient_name": recipient,
                    "total_approved": 0,
                    "total_paid": 0,
                    "support_count": 0,
                    "ministries": set(),
                }

            recipient_totals[recipient]["total_approved"] += attrs.get("amount_approved", 0) or 0
            recipient_totals[recipient]["total_paid"] += attrs.get("amount_paid", 0) or 0
            recipient_totals[recipient]["support_count"] += 1
            ministry = attrs.get("ministry", "")
            if ministry:
                recipient_totals[recipient]["ministries"].add(ministry)

        # Convert sets to lists for JSON
        results = list(recipient_totals.values())
        for r in results:
            r["ministries"] = list(r["ministries"])

        return sorted(results, key=lambda x: -x["total_approved"])[:limit]
