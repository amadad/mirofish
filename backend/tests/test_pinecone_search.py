"""Tests for Pinecone search — uses mocks since we don't connect to real Pinecone in tests."""
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pinecone_search import PineconeSearchService


def test_namespace_generation():
    service = PineconeSearchService.__new__(PineconeSearchService)
    service.namespace_prefix = ""
    assert service._namespace("graph-123", "nodes") == "nodes_graph-123"
    assert service._namespace("graph/special!", "edges") == "edges_graph_special_"


def test_vector_id_deterministic():
    service = PineconeSearchService.__new__(PineconeSearchService)
    id1 = service._vector_id("g1", "n1", "node")
    id2 = service._vector_id("g1", "n1", "node")
    id3 = service._vector_id("g1", "n2", "node")
    assert id1 == id2  # Same inputs = same ID
    assert id1 != id3  # Different inputs = different ID


def test_is_available_without_key():
    service = PineconeSearchService.__new__(PineconeSearchService)
    service.api_key = ""
    assert service.is_available is False

    service.api_key = "pc-test-key"
    assert service.is_available is True


def test_search_returns_hybrid_results():
    """Test search with mocked Pinecone index."""
    service = PineconeSearchService.__new__(PineconeSearchService)
    service.api_key = "test-key"
    service.index_name = "test"
    service.namespace_prefix = ""
    service.model_name = "BAAI/bge-m3"

    # Mock the model
    mock_model = MagicMock()
    mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
    service._model = mock_model

    # Mock the index
    mock_index = MagicMock()
    mock_index.query.return_value = {
        "matches": [
            {
                "id": "vec1",
                "score": 0.95,
                "metadata": {
                    "id": "node_1",
                    "name": "Test Entity",
                    "text": "This is a test entity",
                    "source_type": "node",
                },
            }
        ]
    }
    service._index = mock_index

    results = service.search("graph_1", "test query", limit=5, scope="nodes")
    assert len(results) == 1
    assert results[0].name == "Test Entity"
    assert results[0].score == 0.95


def test_close():
    service = PineconeSearchService.__new__(PineconeSearchService)
    service._index = MagicMock()
    service._pc = MagicMock()
    service.close()
    assert service._index is None
    assert service._pc is None
