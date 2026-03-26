"""MK topic analysis — aggregate speech topics, votes, and bill sponsorships.

Builds a topic profile for each MK based on:
1. Protocol speeches (what they talk about)
2. Bills proposed (what legislation they push)
3. Committee memberships (what they oversee)
4. Voting patterns (what they vote for/against)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .ontology import KNESSET_TOPICS

logger = logging.getLogger("mirofish.knesset.topic_analyzer")


class TopicAnalyzer:
    """Analyze MK topic profiles from graph data."""

    def __init__(self, graph_storage=None):
        self.graph_storage = graph_storage

    def analyze_mk_topics(self, mk_id: str) -> Dict[str, Any]:
        """Build comprehensive topic profile for an MK."""
        if self.graph_storage is None:
            return {"error": "No graph storage"}

        # Aggregate from SPOKE_ABOUT edges
        spoke_topics = defaultdict(float)
        for edge in self.graph_storage.get_edges(source_id=mk_id, relation="SPOKE_ABOUT"):
            topic_id = edge.get("target_id", "").replace("topic_", "")
            spoke_topics[topic_id] += edge.get("weight", 1.0)

        # Aggregate from proposed bills' categories
        bill_topics = defaultdict(int)
        for edge in self.graph_storage.get_edges(source_id=mk_id, relation="PROPOSED"):
            bill = self.graph_storage.get_node(edge.get("target_id", ""))
            if bill:
                category = bill.get("attributes", {}).get("category", "")
                if category:
                    bill_topics[category] += 1

        # Aggregate from committee memberships
        committee_topics: List[str] = []
        for edge in self.graph_storage.get_edges(source_id=mk_id, relation="SITS_ON"):
            committee = self.graph_storage.get_node(edge.get("target_id", ""))
            if committee:
                for topic in committee.get("attributes", {}).get("topics", []):
                    committee_topics.append(topic)

        # Combine all signals
        combined: Dict[str, float] = {}
        for topic, score in spoke_topics.items():
            combined[topic] = combined.get(topic, 0) + score * 0.5
        for topic, count in bill_topics.items():
            combined[topic] = combined.get(topic, 0) + count * 0.3
        for topic in committee_topics:
            combined[topic] = combined.get(topic, 0) + 0.2

        # Normalize
        if combined:
            max_score = max(combined.values())
            combined = {k: round(v / max_score, 3) for k, v in combined.items()}

        # Sort by score
        sorted_topics = sorted(combined.items(), key=lambda x: -x[1])

        return {
            "mk_id": mk_id,
            "top_topics": [
                {
                    "topic": t,
                    "score": s,
                    "label_he": KNESSET_TOPICS.get(t, {}).get("he", t),
                    "label_en": KNESSET_TOPICS.get(t, {}).get("en", t),
                }
                for t, s in sorted_topics[:10]
            ],
            "speech_topics": dict(spoke_topics),
            "bill_topics": dict(bill_topics),
            "committee_topics": committee_topics,
        }

    def analyze_all_mks(self) -> List[Dict[str, Any]]:
        """Build topic profiles for all MKs."""
        if self.graph_storage is None:
            return []

        results = []
        for node in self.graph_storage.list_nodes(label="MK"):
            mk_id = node.get("id", "")
            if mk_id:
                profile = self.analyze_mk_topics(mk_id)
                profile["name"] = node.get("name", "")
                results.append(profile)

        return results
