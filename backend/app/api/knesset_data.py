"""Knesset Data API — REST endpoints for querying the Knesset database.

Provides search across budgets, protocols, bills, MKs, committees,
and collection daemon status. Separate from simulation endpoints.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger("mirofish.api.knesset_data")

knesset_data_bp = Blueprint("knesset_data", __name__, url_prefix="/api/knesset/data")


def _get_graph():
    return current_app.extensions.get("graph_storage")


def _get_pinecone():
    return current_app.extensions.get("pinecone_search")


def _get_daemon():
    return current_app.extensions.get("knesset_daemon")


# ---------------------------------------------------------------------------
# Budget endpoints
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/budget/search", methods=["GET"])
def budget_search():
    """Search budget items by keyword, ministry, or year."""
    q = request.args.get("q", "")
    ministry = request.args.get("ministry", "")
    year = request.args.get("year", type=int)
    limit = request.args.get("limit", 50, type=int)

    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    # Search by label + attributes
    results = []
    for node in graph.list_nodes(label="BudgetLine"):
        attrs = node.get("attributes", {})
        # Filter
        if ministry and ministry not in (attrs.get("ministry", "") or ""):
            continue
        if year and attrs.get("year") != year:
            continue
        if q and q not in (node.get("name", "") + " " + node.get("summary", "")):
            continue
        results.append(node)
        if len(results) >= limit:
            break

    return jsonify({"items": results, "total": len(results)})


@knesset_data_bp.route("/budget/<code>", methods=["GET"])
def budget_detail(code: str):
    """Get a budget line by its code."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    # Search for node with matching budget_code
    for node in graph.list_nodes(label="BudgetLine"):
        if node.get("attributes", {}).get("budget_code") == code:
            # Get children (sub-items)
            children = graph.get_edges(source_id=node["id"], relation="BUDGET_UNDER")
            return jsonify({"item": node, "children": children})

    return jsonify({"error": "Budget code not found"}), 404


@knesset_data_bp.route("/budget/ministry/<name>", methods=["GET"])
def budget_by_ministry(name: str):
    """Get all budget lines for a ministry."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    results = []
    for node in graph.list_nodes(label="BudgetLine"):
        if name in (node.get("attributes", {}).get("ministry", "") or ""):
            results.append(node)

    return jsonify({"items": results, "total": len(results), "ministry": name})


# ---------------------------------------------------------------------------
# Support/grant endpoints
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/supports/search", methods=["GET"])
def supports_search():
    """Search government supports/grants."""
    q = request.args.get("q", "")
    limit = request.args.get("limit", 50, type=int)

    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    results = []
    for node in graph.list_nodes(label="BudgetSupport"):
        if q and q not in (node.get("name", "") + " " + node.get("summary", "")):
            continue
        results.append(node)
        if len(results) >= limit:
            break

    return jsonify({"items": results, "total": len(results)})


# ---------------------------------------------------------------------------
# Protocol endpoints
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/protocols/search", methods=["GET"])
def protocols_search():
    """Semantic search across Knesset protocols."""
    q = request.args.get("q", "")
    limit = request.args.get("limit", 20, type=int)

    if not q:
        return jsonify({"error": "Query parameter 'q' required"}), 400

    # Try Pinecone semantic search first
    pinecone = _get_pinecone()
    if pinecone and pinecone.is_available:
        try:
            results = pinecone.search(
                graph_id="knesset",
                query=q,
                limit=limit,
                scope="nodes",
            )
            return jsonify({
                "items": [r.to_dict() for r in results],
                "total": len(results),
                "search_type": "semantic",
            })
        except Exception as e:
            logger.warning("Pinecone search failed, falling back: %s", e)

    # Fallback: graph text search
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "No search backend available"}), 503

    results = []
    for node in graph.list_nodes(label="Protocol"):
        if q in (node.get("name", "") + " " + node.get("summary", "")):
            results.append(node)
            if len(results) >= limit:
                break

    return jsonify({"items": results, "total": len(results), "search_type": "text"})


@knesset_data_bp.route("/protocols/mk/<mk_id>", methods=["GET"])
def protocols_by_mk(mk_id: str):
    """Get all speeches by a specific MK."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    # Find MENTIONED_IN edges from MK to Protocol
    edges = graph.get_edges(source_id=mk_id, relation="MENTIONED_IN")
    protocol_ids = [e.get("target_id") for e in edges]

    protocols = []
    for pid in protocol_ids[:50]:
        node = graph.get_node(pid)
        if node:
            protocols.append(node)

    return jsonify({"mk_id": mk_id, "protocols": protocols, "total": len(protocols)})


# ---------------------------------------------------------------------------
# Bill endpoints
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/bills/search", methods=["GET"])
def bills_search():
    """Search bills by keyword, status, or sponsor."""
    q = request.args.get("q", "")
    status = request.args.get("status", "")
    sponsor = request.args.get("sponsor", "")
    limit = request.args.get("limit", 50, type=int)

    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    results = []
    for node in graph.list_nodes(label="Bill"):
        attrs = node.get("attributes", {})
        if status and attrs.get("status") != status:
            continue
        if sponsor and sponsor not in str(attrs.get("initiators", [])):
            continue
        if q and q not in (node.get("name", "") + " " + node.get("summary", "")):
            continue
        results.append(node)
        if len(results) >= limit:
            break

    return jsonify({"items": results, "total": len(results)})


@knesset_data_bp.route("/bills/<bill_id>/history", methods=["GET"])
def bill_history(bill_id: str):
    """Full legislative history of a bill."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    node = graph.get_node(bill_id)
    if not node:
        return jsonify({"error": "Bill not found"}), 404

    # Get related edges
    proposed_by = graph.get_edges(target_id=bill_id, relation="PROPOSED")
    voted_for = graph.get_edges(target_id=bill_id, relation="VOTED_FOR")
    voted_against = graph.get_edges(target_id=bill_id, relation="VOTED_AGAINST")
    discussed_in = graph.get_edges(source_id=bill_id, relation="DISCUSSED_IN")

    return jsonify({
        "bill": node,
        "proposed_by": proposed_by,
        "voted_for": voted_for,
        "voted_against": voted_against,
        "discussed_in": discussed_in,
    })


# ---------------------------------------------------------------------------
# MK endpoints
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/mk/<mk_id>/profile", methods=["GET"])
def mk_profile(mk_id: str):
    """Full MK profile with all data."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    node = graph.get_node(mk_id)
    if not node:
        return jsonify({"error": "MK not found"}), 404

    # Gather all relationships
    member_of = graph.get_edges(source_id=mk_id, relation="MEMBER_OF")
    proposed = graph.get_edges(source_id=mk_id, relation="PROPOSED")
    voted_for = graph.get_edges(source_id=mk_id, relation="VOTED_FOR")
    voted_against = graph.get_edges(source_id=mk_id, relation="VOTED_AGAINST")
    sits_on = graph.get_edges(source_id=mk_id, relation="SITS_ON")
    spoke_about = graph.get_edges(source_id=mk_id, relation="SPOKE_ABOUT")

    return jsonify({
        "mk": node,
        "member_of": member_of,
        "bills_proposed": proposed,
        "voted_for": voted_for,
        "voted_against": voted_against,
        "committees": sits_on,
        "topics": spoke_about,
    })


@knesset_data_bp.route("/mk/<mk_id>/interests", methods=["GET"])
def mk_interests(mk_id: str):
    """MK's budget interests and lobby connections."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    lobbied_by = graph.get_edges(source_id=mk_id, relation="LOBBIED_BY")
    supports = graph.get_edges(source_id=mk_id, relation="SUPPORTS_TOPIC")
    opposes = graph.get_edges(source_id=mk_id, relation="OPPOSES_TOPIC")

    # Get MK's budget-related votes
    budget_votes = []
    for edge in graph.get_edges(source_id=mk_id, relation="VOTED_FOR"):
        target = graph.get_node(edge.get("target_id", ""))
        if target and target.get("attributes", {}).get("related_budget_codes"):
            budget_votes.append({"bill": target, "vote": "for"})

    return jsonify({
        "mk_id": mk_id,
        "lobbied_by": lobbied_by,
        "supports": supports,
        "opposes": opposes,
        "budget_votes": budget_votes,
    })


@knesset_data_bp.route("/mk/<mk_id>/topics", methods=["GET"])
def mk_topics(mk_id: str):
    """Topic analysis from MK's speeches."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    spoke_about = graph.get_edges(source_id=mk_id, relation="SPOKE_ABOUT")

    # Aggregate topics
    topic_counts: Dict[str, int] = {}
    for edge in spoke_about:
        topic = edge.get("target_id", "")
        topic_counts[topic] = topic_counts.get(topic, 0) + int(edge.get("weight", 1))

    return jsonify({
        "mk_id": mk_id,
        "topics": topic_counts,
        "edges": spoke_about,
    })


# ---------------------------------------------------------------------------
# Committee endpoints
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/committees", methods=["GET"])
def committees_list():
    """List all committees with members."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    committees = graph.list_nodes(label="Committee")
    # Enrich with member count
    for c in committees:
        members = graph.get_edges(target_id=c["id"], relation="SITS_ON")
        c["member_count"] = len(members)

    return jsonify({"items": committees, "total": len(committees)})


# ---------------------------------------------------------------------------
# Topic analysis
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/topics/<topic>/mks", methods=["GET"])
def topic_mks(topic: str):
    """Which MKs care about a specific topic."""
    graph = _get_graph()
    if graph is None:
        return jsonify({"error": "Graph storage not available"}), 503

    supports = graph.get_edges(target_id=topic, relation="SUPPORTS_TOPIC")
    opposes = graph.get_edges(target_id=topic, relation="OPPOSES_TOPIC")
    spoke = graph.get_edges(target_id=topic, relation="SPOKE_ABOUT")

    return jsonify({
        "topic": topic,
        "supporters": supports,
        "opponents": opposes,
        "speakers": spoke,
    })


# ---------------------------------------------------------------------------
# Unified semantic search
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/search", methods=["GET"])
def unified_search():
    """Unified semantic search across all data types."""
    q = request.args.get("q", "")
    limit = request.args.get("limit", 20, type=int)
    entity_type = request.args.get("type", "")

    if not q:
        return jsonify({"error": "Query parameter 'q' required"}), 400

    pinecone = _get_pinecone()
    if pinecone and pinecone.is_available:
        try:
            results = pinecone.search(
                graph_id="knesset",
                query=q,
                limit=limit,
                scope="nodes",
            )
            items = [r.to_dict() for r in results]
            if entity_type:
                items = [i for i in items if i.get("metadata", {}).get("label") == entity_type]
            return jsonify({
                "items": items,
                "total": len(items),
                "search_type": "semantic",
            })
        except Exception as e:
            logger.warning("Pinecone search failed: %s", e)

    return jsonify({"items": [], "total": 0, "search_type": "unavailable"})


# ---------------------------------------------------------------------------
# Collection daemon status & control
# ---------------------------------------------------------------------------

@knesset_data_bp.route("/collection/status", methods=["GET"])
def collection_status():
    """Get daemon health and all source statuses."""
    daemon = _get_daemon()
    if daemon is None:
        return jsonify({"error": "Daemon not initialized", "running": False}), 503

    return jsonify(daemon.get_status())


@knesset_data_bp.route("/collection/trigger/<source_id>", methods=["POST"])
def collection_trigger(source_id: str):
    """Force immediate collection for a source."""
    daemon = _get_daemon()
    if daemon is None:
        return jsonify({"error": "Daemon not initialized"}), 503

    success = daemon.trigger_source(source_id)
    if success:
        return jsonify({"message": f"Triggered collection for {source_id}"})
    return jsonify({"error": f"Source {source_id} not found"}), 404
