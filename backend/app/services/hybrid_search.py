"""
Hybrid Search Service for MiroFish.

Combines semantic (vector) search with BM25 (keyword) search using Qdrant
embedded mode. Provides search quality far beyond simple keyword matching.

Architecture:
  - Qdrant embedded (in-process, no server needed) for vector + sparse storage
  - BGE-M3 or multilingual-e5-large for dense embeddings
  - BM25 via built-in sparse vector support
  - Reciprocal Rank Fusion (RRF) for combining results
  - Optional cross-encoder reranking for maximum quality

Usage:
  service = HybridSearchService(db_path="./data/hybrid_search")
  service.index_nodes(graph_id, nodes)  # Index graph data
  results = service.search(graph_id, "economic instability", limit=10)
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from qdrant_client import QdrantClient, models

logger = logging.getLogger("mirofish.hybrid_search")

# Collection naming
NODES_COLLECTION = "nodes_{graph_id}"
EDGES_COLLECTION = "edges_{graph_id}"

# Embedding config
DEFAULT_MODEL = "BAAI/bge-m3"
FALLBACK_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_DIM = 1024  # BGE-M3 output dimension


@dataclass
class HybridResult:
    """A single hybrid search result."""
    id: str
    name: str
    text: str
    score: float
    source_type: str  # "node" or "edge"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "text": self.text,
            "score": self.score,
            "source_type": self.source_type,
            "metadata": self.metadata,
        }


class BM25Scorer:
    """Lightweight BM25 scorer for sparse ranking (no external deps)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._corpus_size = 0
        self._avg_doc_len = 0.0
        self._doc_freqs: Counter = Counter()  # term -> num docs containing it

    def fit(self, documents: list[str]) -> None:
        """Build IDF statistics from a corpus."""
        self._corpus_size = len(documents)
        total_len = 0
        self._doc_freqs = Counter()
        for doc in documents:
            tokens = self._tokenize(doc)
            total_len += len(tokens)
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._doc_freqs[token] += 1
        self._avg_doc_len = total_len / max(self._corpus_size, 1)

    def score(self, query: str, document: str) -> float:
        """Score a single document against a query using BM25."""
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(document)
        doc_len = len(doc_tokens)
        doc_term_freqs = Counter(doc_tokens)

        score = 0.0
        for term in query_tokens:
            if term not in doc_term_freqs:
                continue
            tf = doc_term_freqs[term]
            df = self._doc_freqs.get(term, 0)
            idf = math.log(
                (self._corpus_size - df + 0.5) / (df + 0.5) + 1.0
            )
            tf_norm = (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * doc_len / max(self._avg_doc_len, 1))
            )
            score += idf * tf_norm
        return score

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple whitespace + punctuation tokenizer."""
        text = text.lower()
        tokens = re.findall(r"\w+", text, re.UNICODE)
        return tokens


class HybridSearchService:
    """
    Hybrid search combining dense embeddings + BM25 keyword matching.

    Uses Qdrant embedded mode (in-process, no server) for vector storage
    and a lightweight BM25 implementation for keyword scoring.
    Results are fused using Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        db_path: str = "./data/hybrid_search",
        model_name: Optional[str] = None,
        semantic_weight: float = 0.6,
    ):
        self.db_path = os.path.abspath(db_path)
        from ..config import Config
        self.model_name = model_name or getattr(Config, "EMBEDDING_MODEL", DEFAULT_MODEL)
        self.semantic_weight = semantic_weight
        self._model = None
        self._reranker = None
        self._bm25_scorers: dict[str, BM25Scorer] = {}  # collection_name -> scorer

        # Initialize Qdrant embedded
        os.makedirs(self.db_path, exist_ok=True)
        self._client = QdrantClient(path=self.db_path)
        logger.info("HybridSearchService initialized at %s", self.db_path)

    @property
    def model(self):
        """Lazy-load embedding model (downloads ~1.7GB on first use)."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            try:
                logger.info("Loading embedding model: %s", self.model_name)
                self._model = SentenceTransformer(self.model_name)
                logger.info("Model loaded: dim=%d", self._model.get_sentence_embedding_dimension())
            except Exception as e:
                logger.warning("Failed to load %s: %s. Trying fallback.", self.model_name, e)
                self._model = SentenceTransformer(FALLBACK_MODEL)
        return self._model

    @property
    def reranker(self):
        """Lazy-load cross-encoder reranker for maximum quality."""
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                logger.info("Loading reranker: BAAI/bge-reranker-v2-m3")
                self._reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
                logger.info("Reranker loaded")
            except Exception as e:
                logger.warning("Failed to load reranker: %s", e)
                self._reranker = False  # Sentinel: tried and failed
        return self._reranker if self._reranker is not False else None

    def _collection_name(self, graph_id: str, source_type: str = "nodes") -> str:
        """Generate collection name for a graph."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", graph_id)
        return f"{source_type}_{safe_id}"

    def _ensure_collection(self, collection_name: str) -> None:
        """Create collection if it doesn't exist."""
        collections = [c.name for c in self._client.get_collections().collections]
        if collection_name not in collections:
            dim = self.model.get_sentence_embedding_dimension()
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("Created collection: %s (dim=%d)", collection_name, dim)

    def _text_id(self, text: str) -> str:
        """Generate a deterministic point ID from text."""
        # Qdrant needs int or UUID — use hash
        return hashlib.md5(text.encode()).hexdigest()

    # ──────────────────────────────────────────────
    # INDEXING
    # ──────────────────────────────────────────────

    def index_nodes(self, graph_id: str, nodes: list[dict]) -> int:
        """Index graph nodes for hybrid search."""
        collection = self._collection_name(graph_id, "nodes")
        self._ensure_collection(collection)

        texts = []
        points = []
        for node in nodes:
            # Build searchable text from all node fields
            parts = [
                node.get("name", ""),
                node.get("label", ""),
                node.get("summary", ""),
            ]
            facts = node.get("facts", [])
            if isinstance(facts, list):
                parts.extend(facts)
            attrs = node.get("attributes", {})
            if isinstance(attrs, dict):
                parts.extend(str(v) for v in attrs.values())

            text = " ".join(p for p in parts if p)
            if not text.strip():
                continue

            texts.append(text)
            embedding = self.model.encode(text, normalize_embeddings=True)

            points.append(models.PointStruct(
                id=len(points),
                vector=embedding.tolist(),
                payload={
                    "id": node.get("id", ""),
                    "name": node.get("name", ""),
                    "label": node.get("label", ""),
                    "text": text,
                    "source_type": "node",
                    "summary": node.get("summary", ""),
                },
            ))

        if points:
            # Batch upsert (Qdrant handles batching internally)
            self._client.upsert(collection_name=collection, points=points)

            # Build BM25 index for keyword scoring
            bm25 = BM25Scorer()
            bm25.fit(texts)
            self._bm25_scorers[collection] = bm25

        logger.info("Indexed %d nodes for graph %s", len(points), graph_id)
        return len(points)

    def index_edges(self, graph_id: str, edges: list[dict]) -> int:
        """Index graph edges for hybrid search."""
        collection = self._collection_name(graph_id, "edges")
        self._ensure_collection(collection)

        texts = []
        points = []
        for edge in edges:
            parts = [
                edge.get("fact", ""),
                edge.get("relation", ""),
            ]
            text = " ".join(p for p in parts if p)
            if not text.strip():
                continue

            texts.append(text)
            embedding = self.model.encode(text, normalize_embeddings=True)

            points.append(models.PointStruct(
                id=len(points),
                vector=embedding.tolist(),
                payload={
                    "id": edge.get("id", ""),
                    "source_id": edge.get("source_id", ""),
                    "target_id": edge.get("target_id", ""),
                    "relation": edge.get("relation", ""),
                    "fact": edge.get("fact", ""),
                    "text": text,
                    "source_type": "edge",
                    "is_expired": bool(edge.get("expired_at")),
                    "is_invalid": bool(edge.get("invalid_at")),
                },
            ))

        if points:
            self._client.upsert(collection_name=collection, points=points)

            bm25 = BM25Scorer()
            bm25.fit(texts)
            self._bm25_scorers[collection] = bm25

        logger.info("Indexed %d edges for graph %s", len(points), graph_id)
        return len(points)

    def index_graph(self, graph_id: str, nodes: list[dict], edges: list[dict]) -> dict:
        """Index both nodes and edges for a graph."""
        n_nodes = self.index_nodes(graph_id, nodes)
        n_edges = self.index_edges(graph_id, edges)
        return {"nodes_indexed": n_nodes, "edges_indexed": n_edges}

    # ──────────────────────────────────────────────
    # SEARCH
    # ──────────────────────────────────────────────

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "both",
        include_expired: bool = False,
        semantic_weight: Optional[float] = None,
        rerank: Optional[bool] = None,
    ) -> list[HybridResult]:
        """
        Hybrid search: semantic + BM25 with RRF fusion.

        Args:
            graph_id: Graph to search in
            query: Search query (any language)
            limit: Max results to return
            scope: "nodes", "edges", or "both"
            include_expired: Include expired/invalid edges
            semantic_weight: Override default semantic vs keyword weight
            rerank: Whether to apply cross-encoder reranking

        Returns:
            List of HybridResult sorted by relevance
        """
        if rerank is None:
            from ..config import Config
            rerank = getattr(Config, "ENABLE_RERANKING", True)
        weight = semantic_weight or self.semantic_weight
        all_results: list[HybridResult] = []

        # Search in requested scope
        if scope in ("nodes", "both"):
            node_results = self._search_collection(
                graph_id, query, "nodes", limit=limit * 3, semantic_weight=weight
            )
            all_results.extend(node_results)

        if scope in ("edges", "both"):
            edge_results = self._search_collection(
                graph_id, query, "edges", limit=limit * 3, semantic_weight=weight
            )
            # Filter expired if requested
            if not include_expired:
                edge_results = [
                    r for r in edge_results
                    if not r.metadata.get("is_expired") and not r.metadata.get("is_invalid")
                ]
            all_results.extend(edge_results)

        # Sort by hybrid score
        all_results.sort(key=lambda r: r.score, reverse=True)

        # Optional: Cross-encoder reranking for top results
        if rerank and len(all_results) > 1:
            all_results = self._rerank_results(query, all_results, top_n=limit * 2)

        return all_results[:limit]

    def _search_collection(
        self,
        graph_id: str,
        query: str,
        source_type: str,
        limit: int = 30,
        semantic_weight: float = 0.6,
    ) -> list[HybridResult]:
        """Search a single collection with hybrid scoring."""
        collection = self._collection_name(graph_id, source_type)

        # Check if collection exists
        collections = [c.name for c in self._client.get_collections().collections]
        if collection not in collections:
            return []

        # 1. Semantic search via Qdrant
        query_embedding = self.model.encode(query, normalize_embeddings=True)
        semantic_results = self._client.query_points(
            collection_name=collection,
            query=query_embedding.tolist(),
            limit=limit,
        ).points

        # Build semantic rank map: id -> rank position
        semantic_ranks = {}
        for rank, hit in enumerate(semantic_results):
            key = hit.payload.get("id", str(hit.id))
            semantic_ranks[key] = rank

        # 2. BM25 keyword scoring
        bm25 = self._bm25_scorers.get(collection)
        bm25_ranks = {}
        if bm25:
            # Score all results against BM25
            scored = []
            for hit in semantic_results:
                text = hit.payload.get("text", "")
                bm25_score = bm25.score(query, text)
                scored.append((hit, bm25_score))
            # Sort by BM25 score descending
            scored.sort(key=lambda x: x[1], reverse=True)
            for rank, (hit, _) in enumerate(scored):
                key = hit.payload.get("id", str(hit.id))
                bm25_ranks[key] = rank

        # 3. Reciprocal Rank Fusion (RRF)
        k = 60  # RRF constant
        results = []
        for hit in semantic_results:
            key = hit.payload.get("id", str(hit.id))
            sem_rank = semantic_ranks.get(key, limit)
            bm25_rank = bm25_ranks.get(key, limit)

            # RRF score: weighted combination
            rrf_semantic = 1.0 / (k + sem_rank)
            rrf_keyword = 1.0 / (k + bm25_rank)
            hybrid_score = (
                semantic_weight * rrf_semantic
                + (1 - semantic_weight) * rrf_keyword
            )

            results.append(HybridResult(
                id=hit.payload.get("id", str(hit.id)),
                name=hit.payload.get("name", hit.payload.get("relation", "")),
                text=hit.payload.get("text", ""),
                score=hybrid_score,
                source_type=source_type.rstrip("s"),  # "nodes" -> "node"
                metadata={
                    k: v for k, v in hit.payload.items()
                    if k not in ("text",)
                },
            ))

        return results

    def _rerank_results(
        self,
        query: str,
        results: list[HybridResult],
        top_n: int = 20,
    ) -> list[HybridResult]:
        """Apply cross-encoder reranking for maximum quality."""
        reranker = self.reranker
        if not reranker or len(results) <= 1:
            return results

        # Prepare pairs for cross-encoder
        candidates = results[:min(len(results), top_n)]
        pairs = [(query, r.text) for r in candidates]

        try:
            scores = reranker.predict(pairs)
            for result, score in zip(candidates, scores):
                # Blend reranker score with original hybrid score
                result.score = 0.7 * float(score) + 0.3 * result.score
            candidates.sort(key=lambda r: r.score, reverse=True)
            # Append any remaining results that weren't reranked
            reranked_ids = {r.id for r in candidates}
            remaining = [r for r in results if r.id not in reranked_ids]
            return candidates + remaining
        except Exception as e:
            logger.warning("Reranking failed: %s", e)
            return results

    # ──────────────────────────────────────────────
    # UTILITIES
    # ──────────────────────────────────────────────

    def delete_graph_index(self, graph_id: str) -> None:
        """Remove all search indexes for a graph."""
        for source_type in ("nodes", "edges"):
            collection = self._collection_name(graph_id, source_type)
            try:
                self._client.delete_collection(collection)
                self._bm25_scorers.pop(collection, None)
                logger.info("Deleted collection: %s", collection)
            except Exception:
                pass

    def get_stats(self, graph_id: str) -> dict:
        """Get index statistics for a graph."""
        stats = {}
        for source_type in ("nodes", "edges"):
            collection = self._collection_name(graph_id, source_type)
            try:
                info = self._client.get_collection(collection)
                stats[source_type] = {
                    "points": info.points_count,
                    "vectors": info.vectors_count,
                    "status": info.status.value,
                }
            except Exception:
                stats[source_type] = {"points": 0, "vectors": 0, "status": "not_indexed"}
        return stats

    def is_indexed(self, graph_id: str) -> bool:
        """Check if a graph has been indexed for hybrid search."""
        collections = [c.name for c in self._client.get_collections().collections]
        nodes_col = self._collection_name(graph_id, "nodes")
        return nodes_col in collections

    def close(self) -> None:
        """Clean up resources."""
        if self._client:
            self._client.close()
