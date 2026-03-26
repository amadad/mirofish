"""RZMAPPER → MIROFISH entity migration.

One-time import of RZMAPPER's 20,000+ entities and relationships
into MIROFISH's KuzuDB graph and Pinecone vector index.

Usage:
    migrator = RZMapperMigrator(graph_storage, pinecone_service)
    result = migrator.collect_incremental()  # runs full migration
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.rzmapper_migrator")

# Path to RZMAPPER entities
RZMAPPER_ENTITIES_DIR = os.path.join(
    os.path.dirname(__file__), "../../../../..", "RZMAPPER", "data", "entities"
)
RZMAPPER_SNAPSHOT = os.path.join(
    os.path.dirname(__file__), "../../../../..",
    "RZMAPPER", "dashboard", "public", "data", "snapshot.json"
)

# Entity type mapping: RZMAPPER → MIROFISH graph labels
TYPE_MAP = {
    "person": "Person",
    "organization": "Organization",
    "location": "Location",
    "event": "Event",
    "funding": "BudgetSupport",
    "ideology": "Topic",
}

# Subtype → label upgrades (more specific labels for known subtypes)
SUBTYPE_UPGRADES = {
    "politician": "MK",
    "party": "Faction",
    "settlement": "Location",
    "yeshiva": "Organization",
    "ngo": "Organization",
    "rabbi": "Person",
}


class RZMapperMigrator(BaseKnessetCollector):
    """Migrates RZMAPPER entities into MIROFISH KuzuDB + Pinecone."""

    SOURCE_ID = "rzmapper:import"

    def __init__(
        self,
        graph_storage=None,
        pinecone_service=None,
        entities_dir: Optional[str] = None,
        snapshot_path: Optional[str] = None,
    ):
        super().__init__(graph_storage, pinecone_service)
        self.entities_dir = entities_dir or RZMAPPER_ENTITIES_DIR
        self.snapshot_path = snapshot_path or RZMAPPER_SNAPSHOT

    def get_source_id(self) -> str:
        return self.SOURCE_ID

    def collect_incremental(
        self, cursor_state: Optional[Dict[str, Any]] = None
    ) -> CollectionResult:
        """Run the full migration."""
        items_new = 0
        items_updated = 0
        items_skipped = 0
        errors: List[str] = []

        # Phase 1: Import entity JSON files
        if os.path.isdir(self.entities_dir):
            entity_files = [
                f for f in os.listdir(self.entities_dir)
                if f.endswith(".json")
            ]
            logger.info("Found %d entity files in %s", len(entity_files), self.entities_dir)

            batch_texts: List[Dict[str, Any]] = []

            for i, filename in enumerate(entity_files):
                filepath = os.path.join(self.entities_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entity = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    items_skipped += 1
                    if items_skipped <= 10:
                        errors.append(f"Failed to read {filename}: {e}")
                    continue

                node = self._entity_to_node(entity)
                if node is None:
                    items_skipped += 1
                    continue

                # Upsert into graph
                if self.graph_storage:
                    existing = self.graph_storage.get_node(node["id"])
                    if existing:
                        self._merge_node(existing, node)
                        self.graph_storage.update_node(node["id"], node)
                        items_updated += 1
                    else:
                        self.graph_storage.add_node(node)
                        items_new += 1

                # Collect for Pinecone batch indexing
                text = self._node_to_text(node)
                if text:
                    batch_texts.append({
                        "id": node["id"],
                        "text": text,
                        "metadata": {
                            "entity_type": node.get("label", ""),
                            "name_he": node.get("name", ""),
                            "source": "rzmapper",
                        },
                    })

                if (i + 1) % 500 == 0:
                    logger.info("Processed %d/%d entities", i + 1, len(entity_files))

            logger.info(
                "Entity import: %d new, %d updated, %d skipped",
                items_new, items_updated, items_skipped,
            )
        else:
            logger.warning("RZMAPPER entities dir not found: %s", self.entities_dir)

        # Phase 2: Import relationships from snapshot
        edges_imported = self._import_relationships()
        logger.info("Imported %d relationships from snapshot", edges_imported)

        error_msg = "; ".join(errors[:5]) if errors else None
        return CollectionResult(
            source_id=self.SOURCE_ID,
            items_new=items_new,
            items_updated=items_updated,
            items_skipped=items_skipped,
            error=error_msg,
            new_cursor={"completed": True, "entities": items_new + items_updated},
        )

    def _entity_to_node(self, entity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Map RZMAPPER entity schema → KuzuDB node dict."""
        entity_type = entity.get("entity_type", "")
        subtype = entity.get("subtype", "")
        name_he = entity.get("name_he", "")
        entity_id = entity.get("id", "")

        if not name_he or not entity_id:
            return None

        # Determine graph label
        label = SUBTYPE_UPGRADES.get(subtype) or TYPE_MAP.get(entity_type, "Entity")

        # Build attributes dict (everything that doesn't map to top-level fields)
        attributes: Dict[str, Any] = {}
        for key in ["name_en", "subtype", "influence_score", "confidence",
                     "focus_areas", "properties", "sanctions", "ratings",
                     "data_source", "collected_at"]:
            if key in entity and entity[key]:
                attributes[key] = entity[key]

        # Flatten properties into attributes
        props = entity.get("properties", {})
        if isinstance(props, dict):
            for k, v in props.items():
                if k not in attributes:
                    attributes[k] = v

        # Build facts from timeline
        facts: List[str] = []
        for event in entity.get("timeline", []):
            year = event.get("year", "")
            desc = event.get("event", "")
            if year and desc:
                facts.append(f"{year}: {desc}")

        # Sources metadata
        sources = entity.get("sources", [])
        if sources:
            attributes["sources"] = sources

        return {
            "id": f"rz_{entity_id}",
            "name": name_he,
            "label": label,
            "summary": (entity.get("description_he", "") or "")[:5000],
            "facts": facts,
            "attributes": attributes,
        }

    def _merge_node(self, existing: Dict[str, Any], new: Dict[str, Any]) -> None:
        """Merge new node data into existing node (in-place on `new`)."""
        # Merge attributes
        existing_attrs = existing.get("attributes", {})
        new_attrs = new.get("attributes", {})
        merged = {**existing_attrs, **new_attrs}
        new["attributes"] = merged

        # Merge facts (deduplicate)
        existing_facts = set(existing.get("facts", []))
        new_facts = new.get("facts", [])
        new["facts"] = list(existing_facts | set(new_facts))

        # Keep longer summary
        if len(existing.get("summary", "")) > len(new.get("summary", "")):
            new["summary"] = existing["summary"]

    def _node_to_text(self, node: Dict[str, Any]) -> str:
        """Build searchable text from a node for Pinecone indexing."""
        parts = [
            node.get("name", ""),
            node.get("label", ""),
            node.get("summary", ""),
        ]
        facts = node.get("facts", [])
        if facts:
            parts.extend(facts[:20])

        attrs = node.get("attributes", {})
        name_en = attrs.get("name_en", "")
        if name_en:
            parts.append(name_en)

        return " ".join(p for p in parts if p)[:4000]

    def _import_relationships(self) -> int:
        """Import relationships from RZMAPPER snapshot.json."""
        if not os.path.isfile(self.snapshot_path):
            logger.warning("Snapshot not found: %s", self.snapshot_path)
            return 0

        if self.graph_storage is None:
            return 0

        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read snapshot: %s", e)
            return 0

        edges = snapshot.get("edges", [])
        imported = 0

        # Build node ID mapping: snapshot uses sequential IDs (person_0, etc.)
        # We need to map to our rz_ prefixed IDs
        node_map: Dict[str, str] = {}
        for node in snapshot.get("nodes", []):
            old_id = node.get("id", "")
            # Try to find our imported node by name
            name_he = node.get("name_he", "")
            if name_he:
                # Build deterministic rz_ ID from original
                # The snapshot IDs are sequential, but entities have original IDs
                entity_id = node.get("original_id") or old_id
                node_map[old_id] = f"rz_{entity_id}"

        for edge in edges:
            source_id = node_map.get(edge.get("source", ""), edge.get("source", ""))
            target_id = node_map.get(edge.get("target", ""), edge.get("target", ""))
            rel_type = edge.get("relationship_type", "RELATED_TO")

            if not source_id or not target_id:
                continue

            edge_data = {
                "id": f"rz_edge_{imported}",
                "source_id": source_id,
                "target_id": target_id,
                "relation": rel_type,
                "fact": edge.get("evidence_he", ""),
                "weight": edge.get("weight", 1.0),
                "attributes": {
                    "confidence": edge.get("confidence", 0.5),
                    "source": "rzmapper",
                },
            }

            try:
                self.upsert_edge(edge_data)
                imported += 1
            except Exception as e:
                if imported < 5:
                    logger.warning("Edge import error: %s", e)

        return imported
