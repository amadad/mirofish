"""Knesset Semantic Pipeline — text processing for Hebrew political content.

Processes raw text through:
1. Hebrew normalization (strip niqqud, normalize whitespace)
2. Entity extraction (regex + dictionary from HebrewNLP)
3. Topic classification (keyword-based + LLM fallback)
4. Sentiment/stance analysis
5. Relationship mining (co-occurrence, vote patterns)

Used by collectors to enrich data before storing in graph + Pinecone.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .hebrew_nlp import HebrewNLP
from .ontology import TOPIC_KEYWORDS, KNESSET_TOPICS

logger = logging.getLogger("mirofish.knesset.semantic")


class SemanticPipeline:
    """Process Hebrew political text into structured knowledge."""

    def __init__(self, graph_storage=None, llm_client=None):
        self.graph_storage = graph_storage
        self.llm_client = llm_client
        self.nlp = HebrewNLP(graph_storage)

    def process_text(
        self,
        text: str,
        source_type: str = "protocol",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Full pipeline: text → structured extraction.

        Returns:
            {
                "entities": {...},
                "topics": [{"topic": str, "score": float}],
                "sentiment": str,
                "stance": str,
                "relationships": [...],
                "summary": str,
            }
        """
        metadata = metadata or {}

        # 1. Normalize
        clean = self._normalize(text)

        # 2. Extract entities via HebrewNLP
        entities = self.nlp.extract_entities(clean)

        # 3. Classify topics
        topics = self.classify_topics(clean)

        # 4. Analyze sentiment/stance
        stance = self.nlp.classify_political_stance(clean)
        vote_intent = self.nlp.extract_vote_intent(clean)

        # 5. Mine relationships
        relationships = self._mine_relationships(
            entities, topics, metadata
        )

        return {
            "entities": entities,
            "topics": topics,
            "stance": stance,
            "vote_intent": vote_intent,
            "relationships": relationships,
            "text_length": len(clean),
        }

    # ------------------------------------------------------------------
    # Text normalization
    # ------------------------------------------------------------------

    def _normalize(self, text: str) -> str:
        """Normalize Hebrew text for processing."""
        # Strip niqqud
        text = HebrewNLP._strip_niqqud(text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Remove very long repeated characters
        text = re.sub(r"(.)\1{5,}", r"\1\1\1", text)
        return text

    # ------------------------------------------------------------------
    # Topic classification
    # ------------------------------------------------------------------

    def classify_topics(
        self, text: str, top_n: int = 3
    ) -> List[Dict[str, Any]]:
        """Classify text into Knesset topics using keyword matching.

        Returns sorted list of {topic, score, label_he, label_en}.
        """
        text_lower = text.lower() if text else ""
        scores: Dict[str, float] = {}

        for topic, keywords in TOPIC_KEYWORDS.items():
            count = 0
            for kw in keywords:
                # Count occurrences
                count += text_lower.count(kw)
            if count > 0:
                # Normalize: log scale to avoid one dominant keyword
                import math
                scores[topic] = math.log1p(count)

        if not scores:
            return []

        # Normalize to 0-1
        max_score = max(scores.values())
        results = []
        for topic, score in sorted(scores.items(), key=lambda x: -x[1]):
            topic_info = KNESSET_TOPICS.get(topic, {})
            results.append({
                "topic": topic,
                "score": round(score / max_score, 3),
                "label_he": topic_info.get("he", topic),
                "label_en": topic_info.get("en", topic),
            })

        return results[:top_n]

    # ------------------------------------------------------------------
    # Relationship mining
    # ------------------------------------------------------------------

    def _mine_relationships(
        self,
        entities: Dict[str, Any],
        topics: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Extract typed relationships from entity extractions."""
        relationships: List[Dict[str, Any]] = []

        mk_mentions = entities.get("mk_mentions", [])
        faction_mentions = entities.get("faction_mentions", [])
        speaker_mk_id = metadata.get("speaker_mk_id")

        # MK → Topic: SPOKE_ABOUT
        if speaker_mk_id and topics:
            for topic in topics:
                relationships.append({
                    "source_id": speaker_mk_id,
                    "target_id": f"topic_{topic['topic']}",
                    "relation": "SPOKE_ABOUT",
                    "weight": topic["score"],
                })

        # MK co-occurrence in same speech → implicit alliance
        if len(mk_mentions) >= 2:
            for i, mk_a in enumerate(mk_mentions):
                for mk_b in mk_mentions[i + 1:]:
                    if mk_a.get("mk_id") and mk_b.get("mk_id"):
                        relationships.append({
                            "source_id": mk_a["mk_id"],
                            "target_id": mk_b["mk_id"],
                            "relation": "MENTIONED_TOGETHER",
                            "weight": 0.3,
                        })

        # MK mentioning faction → relates to
        if speaker_mk_id:
            for faction in faction_mentions:
                if faction.get("faction_id"):
                    relationships.append({
                        "source_id": speaker_mk_id,
                        "target_id": faction["faction_id"],
                        "relation": "MENTIONED",
                        "weight": 0.5,
                    })

        return relationships

    # ------------------------------------------------------------------
    # Protocol speech segmentation
    # ------------------------------------------------------------------

    @staticmethod
    def segment_protocol(text: str) -> List[Dict[str, str]]:
        """Split a Knesset protocol into speaker segments.

        Detects patterns like:
        - "היו\"ר NAME:" (chairperson)
        - "NAME:" (regular speaker at line start)
        - "ח\"כ NAME:" (MK prefix)
        - "השר NAME:" / "שר NAME:" (minister)

        Returns list of {speaker, role, text}.
        """
        # Pattern: Hebrew name at start of line, followed by colon
        speaker_pattern = re.compile(
            r'^(?:'
            r'(?:היו"ר|יו"ר)\s+([\u05d0-\u05ea\s\-]+)'  # chairperson
            r'|(?:ח"כ)\s+([\u05d0-\u05ea\s\-]+)'          # MK
            r'|(?:השר|שר|סגן השר)\s+([\u05d0-\u05ea\s\-]+)'  # minister
            r'|([\u05d0-\u05ea\s\-]{4,30})'                # plain name
            r')\s*:',
            re.MULTILINE | re.UNICODE
        )

        segments: List[Dict[str, str]] = []
        matches = list(speaker_pattern.finditer(text))

        for i, match in enumerate(matches):
            # Determine speaker name and role
            if match.group(1):
                speaker = match.group(1).strip()
                role = "chair"
            elif match.group(2):
                speaker = match.group(2).strip()
                role = "MK"
            elif match.group(3):
                speaker = match.group(3).strip()
                role = "minister"
            else:
                speaker = match.group(4).strip() if match.group(4) else ""
                role = "unknown"

            # Extract text until next speaker
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment_text = text[start:end].strip()

            if speaker and segment_text:
                segments.append({
                    "speaker": speaker,
                    "role": role,
                    "text": segment_text,
                })

        return segments

    # ------------------------------------------------------------------
    # Budget text analysis
    # ------------------------------------------------------------------

    @staticmethod
    def extract_budget_amounts(text: str) -> List[Dict[str, Any]]:
        """Extract monetary amounts from Hebrew text.

        Looks for patterns like:
        - "100 מיליון ש\"ח" / "100 מיליון שקל"
        - "1.5 מיליארד"
        - "500,000 ₪"
        """
        amounts: List[Dict[str, Any]] = []

        patterns = [
            # X מיליארד
            (r"([\d,.]+)\s*מיליארד(?:\s*(?:ש\"ח|שקל|₪))?", 1e9),
            # X מיליון
            (r"([\d,.]+)\s*מיליון(?:\s*(?:ש\"ח|שקל|₪))?", 1e6),
            # X אלף
            (r"([\d,.]+)\s*אלף(?:\s*(?:ש\"ח|שקל|₪))?", 1e3),
            # X ₪ or X ש"ח
            (r"([\d,]+)\s*(?:₪|ש\"ח|שקל)", 1),
        ]

        for pattern, multiplier in patterns:
            for m in re.finditer(pattern, text):
                raw = m.group(1).replace(",", "")
                try:
                    value = float(raw) * multiplier
                    context_start = max(0, m.start() - 30)
                    context_end = min(len(text), m.end() + 30)
                    amounts.append({
                        "amount_nis": value,
                        "raw": m.group(0),
                        "context": text[context_start:context_end].strip(),
                    })
                except ValueError:
                    continue

        return amounts
