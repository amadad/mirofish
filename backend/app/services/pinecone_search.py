"""Pinecone cloud search backend for MiroFish.

Alternative to Qdrant embedded for production/cloud deployments.
Uses Pinecone serverless for unlimited scale vector search.

Usage:
    service = PineconeSearchService()
    service.index_nodes(graph_id, nodes)
    results = service.search(graph_id, "economic instability", limit=10)

Requires:
    PINECONE_API_KEY in .env
    PINECONE_INDEX_NAME in .env (default: "mirofish")
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("mirofish.pinecone_search")

# Reuse HybridResult from existing search
try:
    from .hybrid_search import HybridResult, DEFAULT_MODEL, FALLBACK_MODEL
except ImportError:
    @dataclass
    class HybridResult:
        id: str
        name: str
        text: str
        score: float
        source_type: str
        metadata: dict = field(default_factory=dict)

        def to_dict(self) -> dict:
            return {
                "id": self.id, "name": self.name, "text": self.text,
                "score": self.score, "source_type": self.source_type,
                "metadata": self.metadata,
            }

    DEFAULT_MODEL = "BAAI/bge-m3"
    FALLBACK_MODEL = "intfloat/multilingual-e5-large"


class PineconeSearchService:
    """Cloud-based vector search using Pinecone.

    Mirrors the HybridSearchService API for drop-in replacement.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        index_name: Optional[str] = None,
        model_name: Optional[str] = None,
        namespace_prefix: str = "",
    ):
        self.api_key = api_key or os.environ.get("PINECONE_API_KEY", "")
        self.index_name = index_name or os.environ.get("PINECONE_INDEX_NAME", "mirofish")
        self.namespace_prefix = namespace_prefix
        self._model = None
        self._index = None
        self._pc = None

        from ..config import Config
        self.model_name = model_name or getattr(Config, "EMBEDDING_MODEL", DEFAULT_MODEL)

        if not self.api_key:
            logger.warning("PINECONE_API_KEY not set — Pinecone search unavailable")

    @property
    def model(self):
        """Lazy-load embedding model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            try:
                self._model = SentenceTransformer(self.model_name)
            except Exception:
                self._model = SentenceTransformer(FALLBACK_MODEL)
        return self._model

    @property
    def index(self):
        """Lazy-connect to Pinecone index."""
        if self._index is None:
            if not self.api_key:
                raise RuntimeError("PINECONE_API_KEY not configured")
            try:
                from pinecone import Pinecone
                self._pc = Pinecone(api_key=self.api_key)

                # Check if index exists, create if not
                existing = [idx.name for idx in self._pc.list_indexes()]
                if self.index_name not in existing:
                    from pinecone import ServerlessSpec
                    dim = self.model.get_sentence_embedding_dimension()
                    self._pc.create_index(
                        name=self.index_name,
                        dimension=dim,
                        metric="cosine",
                        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                    )
                    logger.info("Created Pinecone index: %s (dim=%d)", self.index_name, dim)

                self._index = self._pc.Index(self.index_name)
                logger.info("Connected to Pinecone index: %s", self.index_name)
            except ImportError:
                raise ImportError(
                    "pinecone package required. Install with: pip install pinecone"
                )
        return self._index

    def _namespace(self, graph_id: str, source_type: str) -> str:
        """Generate namespace for a graph's data."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", graph_id)
        return f"{self.namespace_prefix}{source_type}_{safe_id}"

    def _vector_id(self, graph_id: str, item_id: str, source_type: str) -> str:
        """Generate deterministic vector ID."""
        raw = f"{graph_id}:{source_type}:{item_id}"
        return hashlib.md5(raw.encode()).hexdigest()

    # ──────────────────────────────────────────────
    # INDEXING
    # ──────────────────────────────────────────────

    def index_nodes(self, graph_id: str, nodes: List[dict]) -> int:
        """Index graph nodes into Pinecone."""
        namespace = self._namespace(graph_id, "nodes")
        vectors = []

        for node in nodes:
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

            embedding = self.model.encode(text, normalize_embeddings=True).tolist()
            vec_id = self._vector_id(graph_id, node.get("id", ""), "node")

            vectors.append({
                "id": vec_id,
                "values": embedding,
                "metadata": {
                    "id": node.get("id", ""),
                    "name": node.get("name", ""),
                    "label": node.get("label", ""),
                    "text": text[:1000],  # Pinecone metadata limit
                    "source_type": "node",
                    "summary": (node.get("summary", "") or "")[:500],
                    "graph_id": graph_id,
                },
            })

        if vectors:
            # Upsert in batches of 100 (Pinecone limit)
            for i in range(0, len(vectors), 100):
                batch = vectors[i:i + 100]
                self.index.upsert(vectors=batch, namespace=namespace)

        logger.info("Indexed %d nodes for graph %s in Pinecone", len(vectors), graph_id)
        return len(vectors)

    def index_edges(self, graph_id: str, edges: List[dict]) -> int:
        """Index graph edges into Pinecone."""
        namespace = self._namespace(graph_id, "edges")
        vectors = []

        for edge in edges:
            parts = [edge.get("fact", ""), edge.get("relation", "")]
            text = " ".join(p for p in parts if p)
            if not text.strip():
                continue

            embedding = self.model.encode(text, normalize_embeddings=True).tolist()
            vec_id = self._vector_id(graph_id, edge.get("id", ""), "edge")

            vectors.append({
                "id": vec_id,
                "values": embedding,
                "metadata": {
                    "id": edge.get("id", ""),
                    "source_id": edge.get("source_id", ""),
                    "target_id": edge.get("target_id", ""),
                    "relation": edge.get("relation", ""),
                    "fact": (edge.get("fact", "") or "")[:500],
                    "text": text[:1000],
                    "source_type": "edge",
                    "graph_id": graph_id,
                },
            })

        if vectors:
            for i in range(0, len(vectors), 100):
                batch = vectors[i:i + 100]
                self.index.upsert(vectors=batch, namespace=namespace)

        logger.info("Indexed %d edges for graph %s in Pinecone", len(vectors), graph_id)
        return len(vectors)

    def index_graph(self, graph_id: str, nodes: List[dict], edges: List[dict]) -> dict:
        """Index both nodes and edges."""
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
        **kwargs,
    ) -> List[HybridResult]:
        """Search graph data using Pinecone vector similarity."""
        query_embedding = self.model.encode(query, normalize_embeddings=True).tolist()
        all_results: List[HybridResult] = []

        scopes = []
        if scope in ("nodes", "both"):
            scopes.append("nodes")
        if scope in ("edges", "both"):
            scopes.append("edges")

        for source_type in scopes:
            namespace = self._namespace(graph_id, source_type)
            try:
                response = self.index.query(
                    vector=query_embedding,
                    top_k=limit,
                    namespace=namespace,
                    include_metadata=True,
                )

                for match in response.get("matches", []):
                    meta = match.get("metadata", {})
                    all_results.append(HybridResult(
                        id=meta.get("id", match["id"]),
                        name=meta.get("name", meta.get("relation", "")),
                        text=meta.get("text", ""),
                        score=match.get("score", 0.0),
                        source_type=source_type.rstrip("s"),
                        metadata=meta,
                    ))
            except Exception as e:
                logger.warning("Pinecone search failed for %s/%s: %s", graph_id, source_type, e)

        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:limit]

    # ──────────────────────────────────────────────
    # UTILITIES
    # ──────────────────────────────────────────────

    def delete_graph_index(self, graph_id: str) -> None:
        """Remove all vectors for a graph."""
        for source_type in ("nodes", "edges"):
            namespace = self._namespace(graph_id, source_type)
            try:
                self.index.delete(delete_all=True, namespace=namespace)
                logger.info("Deleted namespace: %s", namespace)
            except Exception as e:
                logger.warning("Failed to delete namespace %s: %s", namespace, e)

    def get_stats(self, graph_id: str) -> dict:
        """Get index statistics."""
        try:
            stats = self.index.describe_index_stats()
            result = {}
            for source_type in ("nodes", "edges"):
                ns = self._namespace(graph_id, source_type)
                ns_stats = stats.get("namespaces", {}).get(ns, {})
                result[source_type] = {
                    "vectors": ns_stats.get("vector_count", 0),
                    "status": "indexed" if ns_stats else "not_indexed",
                }
            return result
        except Exception:
            return {"nodes": {"vectors": 0}, "edges": {"vectors": 0}}

    @property
    def is_available(self) -> bool:
        """Check if Pinecone is configured and accessible."""
        return bool(self.api_key)

    def close(self) -> None:
        """Clean up resources."""
        self._index = None
        self._pc = None
