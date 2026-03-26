"""KnessetSim Phase 3 — Historical bill query + precedent analysis.

Uses HybridSearchService for semantic+keyword search over indexed bills,
and LLMRouter for Hebrew-language precedent analysis.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.knesset.historical_query")

# Graph ID used for Knesset bill index
KNESSET_GRAPH_ID = "knesset_bills"


class KnessetHistoricalQuery:
    """Search historical Knesset bills and analyze legislative precedents."""

    def __init__(
        self,
        hybrid_search=None,
        router=None,
    ):
        """
        Args:
            hybrid_search: HybridSearchService instance for bill search.
            router: LLMRouter instance for precedent analysis.
        """
        self._search = hybrid_search
        self._router = router

    # ------------------------------------------------------------------
    # 1. Search similar bills
    # ------------------------------------------------------------------

    def search_similar_bills(
        self,
        query_he: str,
        limit: int = 10,
        graph_id: str = KNESSET_GRAPH_ID,
    ) -> List[dict]:
        """Search indexed bills using hybrid (semantic + BM25) search.

        Args:
            query_he: Hebrew query describing the bill topic / intent.
            limit: Max results to return.
            graph_id: Graph collection to search (default: knesset_bills).

        Returns:
            List of dicts with keys:
                bill_id, title_he, score, status, votes_for, votes_against
        """
        if not self._search:
            logger.warning("No HybridSearchService configured — returning empty results")
            return []

        results = self._search.search(
            graph_id=graph_id,
            query=query_he,
            limit=limit,
            scope="nodes",
        )

        bills: List[dict] = []
        for r in results:
            meta = r.metadata or {}
            bills.append({
                "bill_id": r.id,
                "title_he": r.name or meta.get("label", ""),
                "score": round(r.score, 4),
                "status": meta.get("status", ""),
                "votes_for": meta.get("votes_for", 0),
                "votes_against": meta.get("votes_against", 0),
            })
        return bills

    # ------------------------------------------------------------------
    # 2. Analyze precedents (LLM-powered)
    # ------------------------------------------------------------------

    def analyze_precedents(
        self,
        query_he: str,
        similar_bills: List[dict],
    ) -> dict:
        """Analyze historical precedents for a proposed bill.

        Takes user question + search results, calls LLM with
        task_type="knesset_analysis" for Hebrew-language analysis.

        Args:
            query_he: The user's Hebrew question / bill description.
            similar_bills: Output of search_similar_bills().

        Returns:
            dict with keys:
                analysis_he, probability, key_supporters,
                key_opponents, recommendation

        *** WARNING: This method calls the LLM via router.chat_json().
        *** Do NOT invoke without explicit user approval for the API call.
        """
        if not self._router:
            logger.warning("No LLMRouter configured — returning empty analysis")
            return {
                "analysis_he": "",
                "probability": 0.0,
                "key_supporters": [],
                "key_opponents": [],
                "recommendation": "",
            }

        # Build context from similar bills
        bills_context = "\n".join(
            f"- {b['title_he']} (סטטוס: {b['status']}, "
            f"בעד: {b['votes_for']}, נגד: {b['votes_against']}, "
            f"ציון דמיון: {b['score']})"
            for b in similar_bills
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "אתה מומחה לחקיקה ישראלית ולניתוח תקדימים בכנסת. "
                    "ענה בעברית בלבד. תן ניתוח מבוסס נתונים."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"שאלת המשתמש:\n{query_he}\n\n"
                    f"הצעות חוק דומות שנמצאו:\n{bills_context}\n\n"
                    "נתח את התקדימים וענה בפורמט JSON עם השדות הבאים:\n"
                    '- "analysis_he": ניתוח מפורט בעברית\n'
                    '- "probability": הסתברות להצלחה (0.0 עד 1.0)\n'
                    '- "key_supporters": רשימת שמות תומכים צפויים\n'
                    '- "key_opponents": רשימת שמות מתנגדים צפויים\n'
                    '- "recommendation": המלצה קצרה בעברית'
                ),
            },
        ]

        # ============================================================
        # LLM CALL — requires user approval before invocation.
        # Uses task_type="knesset_analysis" routed by LLMRouter config.
        # ============================================================
        try:
            result = self._router.chat_json(
                task_type="knesset_analysis",
                messages=messages,
                temperature=0.4,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("LLM precedent analysis failed: %s", e)
            return {
                "analysis_he": f"שגיאה בניתוח: {e}",
                "probability": 0.0,
                "key_supporters": [],
                "key_opponents": [],
                "recommendation": "",
            }

        # Normalize output — ensure all expected keys exist
        return {
            "analysis_he": result.get("analysis_he", ""),
            "probability": float(result.get("probability", 0.0)),
            "key_supporters": result.get("key_supporters", []),
            "key_opponents": result.get("key_opponents", []),
            "recommendation": result.get("recommendation", ""),
        }

    # ------------------------------------------------------------------
    # 3. Get bill details from graph
    # ------------------------------------------------------------------

    def get_bill_details(
        self,
        bill_id: str,
        graph_storage=None,
    ) -> dict:
        """Query the knowledge graph for full bill detail.

        Looks up the bill node and its related edges (sponsors, votes)
        in graph_storage.

        Args:
            bill_id: Unique bill identifier.
            graph_storage: GraphStorage instance (optional override;
                           uses self._search graph if not provided).

        Returns:
            dict with keys:
                bill_id, title_he, summary_he, status, category,
                sponsor, votes, related_mks, amendments
        """
        if graph_storage is None:
            logger.warning("No graph_storage provided — returning stub")
            return {"bill_id": bill_id, "error": "no_graph_storage"}

        # Fetch the bill node
        bill_node = graph_storage.get_node(bill_id)
        if not bill_node:
            return {"bill_id": bill_id, "error": "not_found"}

        attrs = bill_node.get("attributes", {})

        # Fetch edges connected to this bill
        edges = graph_storage.get_edges_for_node(bill_id)

        sponsors: List[dict] = []
        vote_edges: List[dict] = []
        related_mks: List[dict] = []

        for edge in edges:
            rel = edge.get("relation", "")
            if rel in ("sponsored", "proposed", "co_sponsored"):
                sponsors.append({
                    "mk_id": edge.get("source_id", ""),
                    "mk_name": edge.get("source_name", ""),
                    "relation": rel,
                })
            elif rel in ("voted_for", "voted_against", "abstained"):
                vote_edges.append({
                    "mk_id": edge.get("source_id", ""),
                    "mk_name": edge.get("source_name", ""),
                    "vote": rel,
                })
            else:
                related_mks.append({
                    "mk_id": edge.get("source_id") or edge.get("target_id", ""),
                    "relation": rel,
                    "fact": edge.get("fact", ""),
                })

        return {
            "bill_id": bill_id,
            "title_he": bill_node.get("name", ""),
            "summary_he": bill_node.get("summary", ""),
            "status": attrs.get("status", ""),
            "category": attrs.get("category", ""),
            "sponsor": sponsors[0] if sponsors else None,
            "co_sponsors": sponsors[1:],
            "votes": vote_edges,
            "related_mks": related_mks,
            "amendments": attrs.get("amendments", []),
        }
