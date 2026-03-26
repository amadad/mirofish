import pytest
import json
import sys
import os

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.resources.llm.cost_tracker import CostTracker


def test_record_call_tracks_tokens():
    tracker = CostTracker()
    tracker.record("groq", "llama-3.3-70b-versatile", input_tokens=1000, output_tokens=500)
    summary = tracker.summary()
    assert summary["total_calls"] == 1
    assert summary["providers"]["groq"]["calls"] == 1
    assert summary["providers"]["groq"]["input_tokens"] == 1000
    assert summary["providers"]["groq"]["output_tokens"] == 500


def test_cost_estimation():
    tracker = CostTracker()
    tracker.set_pricing("groq", input_per_1m=0.59, output_per_1m=0.79)
    tracker.record("groq", "llama-3.3-70b-versatile", input_tokens=1_000_000, output_tokens=1_000_000)
    summary = tracker.summary()
    assert abs(summary["providers"]["groq"]["estimated_cost"] - 1.38) < 0.01


def test_multiple_providers():
    tracker = CostTracker()
    tracker.set_pricing("groq", input_per_1m=0.59, output_per_1m=0.79)
    tracker.set_pricing("anthropic", input_per_1m=15.0, output_per_1m=75.0)
    tracker.record("groq", "llama", input_tokens=100, output_tokens=50)
    tracker.record("anthropic", "opus", input_tokens=200, output_tokens=100)
    summary = tracker.summary()
    assert summary["total_calls"] == 2
    assert len(summary["providers"]) == 2


def test_to_dict_serializable():
    tracker = CostTracker()
    tracker.record("groq", "llama", input_tokens=10, output_tokens=5)
    json.dumps(tracker.summary())  # Should not raise
