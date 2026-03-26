#!/usr/bin/env python3
"""
Import Knesset data from RZMAPPER into MiroFish graph database.

Reads:
  - RZMAPPER/data/entities/knesset_*.json and person_knesset_*.json
  - RZMAPPER/data/raw/knesset/factions.json
  - RZMAPPER/data/raw/knesset/bills.json
  - RZMAPPER/data/raw/knesset/positions.json
  - RZMAPPER/data/raw/knesset/members.json

Writes nodes and edges into a MiroFish JSONStorage graph.

Usage:
    python import_knesset_data.py [--rzmapper-path ../../RZMAPPER] [--graph-dir ../../data/graph]
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: allow importing from MiroFish backend
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.graph_storage import JSONStorage, StorageError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("import_knesset")

NOW = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 25th Knesset coalition / opposition mapping
# ---------------------------------------------------------------------------
COALITION_FACTIONS: Set[str] = {
    "הליכוד",
    "התאחדות הספרדים שומרי תורה",  # Shas — partial match
    "יהדות התורה",
    "הציונות הדתית",  # partial match
    "עוצמה יהודית",  # partial match
    "נעם",  # partial match
}

OPPOSITION_FACTIONS: Set[str] = {
    "יש עתיד",
    "כחול לבן",  # partial match — National Unity
    "ישראל ביתנו",
    "חד\"ש-תע\"ל",
    "רע\"ם",
    "העבודה",
    "בלד",
    "מרצ",
    "הימין הממלכתי",
}


def _faction_camp(faction_name: str) -> Optional[str]:
    """Return 'coalition' or 'opposition' based on faction name substring matching."""
    name = faction_name.strip()
    for keyword in COALITION_FACTIONS:
        if keyword in name:
            return "coalition"
    for keyword in OPPOSITION_FACTIONS:
        if keyword in name:
            return "opposition"
    return None


def _edge_id() -> str:
    return f"e_{uuid.uuid4().hex[:12]}"


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ---------------------------------------------------------------------------
# 1. Load RZMAPPER entity files
# ---------------------------------------------------------------------------

def load_rzmapper_entities(entities_dir: str) -> Dict[int, dict]:
    """
    Scan for knesset_*.json and person_knesset_*.json.
    Deduplicate by knesset_person_id, preferring knesset_*.json (higher quality).
    Returns dict keyed by knesset_person_id.
    """
    entities: Dict[int, dict] = {}

    # Load person_knesset_* first (lower priority)
    person_pattern = os.path.join(entities_dir, "person_knesset_*.json")
    person_files = glob.glob(person_pattern)
    log.info("Found %d person_knesset_*.json files", len(person_files))

    for path in person_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("properties", {}).get("knesset_person_id")
            if pid is None:
                # Try top-level id like "knesset_123"
                raw_id = data.get("id", "")
                if raw_id.startswith("knesset_"):
                    try:
                        pid = int(raw_id.split("_")[1])
                    except (ValueError, IndexError):
                        continue
            if pid is not None:
                entities[int(pid)] = data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: %s", os.path.basename(path), exc)

    # Load knesset_* (higher priority — overwrites person_knesset_*)
    knesset_pattern = os.path.join(entities_dir, "knesset_*.json")
    knesset_files = glob.glob(knesset_pattern)
    log.info("Found %d knesset_*.json files", len(knesset_files))

    for path in knesset_files:
        basename = os.path.basename(path)
        # Skip if this is actually a person_knesset_ file matched by the glob
        if basename.startswith("person_knesset_"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pid = data.get("properties", {}).get("knesset_person_id")
            if pid is None:
                raw_id = data.get("id", "")
                if raw_id.startswith("knesset_"):
                    try:
                        pid = int(raw_id.split("_")[1])
                    except (ValueError, IndexError):
                        continue
            if pid is not None:
                entities[int(pid)] = data  # overwrite lower-quality entry
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: %s", basename, exc)

    log.info("Loaded %d unique MK entities (deduplicated by knesset_person_id)", len(entities))
    return entities


# ---------------------------------------------------------------------------
# 2. Import MKs
# ---------------------------------------------------------------------------

def import_mks(gs: JSONStorage, entities: Dict[int, dict]) -> int:
    """Create MK nodes. Returns count of imported MKs."""
    count = 0
    for pid, entity in entities.items():
        props = entity.get("properties", {})
        name = entity.get("name_he") or entity.get("name", "") or ""
        if not name:
            continue

        node = {
            "id": f"mk_{pid}",
            "name": name,
            "label": "MK",
            "summary": _safe_str(entity.get("description_he", "")),
            "facts": [],
            "attributes": {
                "knesset_person_id": pid,
                "gender": _safe_str(props.get("gender", "")),
                "is_current_mk": bool(props.get("is_current_mk", False)),
                "influence_score": entity.get("influence_score", 0),
                "knesset_nums": props.get("knesset_nums", []),
                "email": _safe_str(props.get("email", "")),
                "name_en": _safe_str(entity.get("name_en", "")),
                "subtype": _safe_str(entity.get("subtype", "politician")),
                "source": "rzmapper_knesset",
            },
            "created_at": NOW,
            "updated_at": NOW,
        }
        try:
            gs.add_node(node)
            count += 1
        except Exception as exc:
            log.warning("Failed to add MK %s (pid=%d): %s", name, pid, exc)

    log.info("Imported %d MK nodes", count)
    return count


# ---------------------------------------------------------------------------
# 3. Import Factions
# ---------------------------------------------------------------------------

def import_factions(gs: JSONStorage, factions_file: str) -> int:
    """Create Faction nodes from raw factions.json. Returns count."""
    if not os.path.exists(factions_file):
        log.warning("Factions file not found: %s", factions_file)
        return 0

    with open(factions_file, "r", encoding="utf-8") as f:
        factions = json.load(f)

    count = 0
    for faction in factions:
        fid = faction.get("FactionID")
        name = _safe_str(faction.get("Name", ""))
        if not fid or not name:
            continue

        node = {
            "id": f"faction_{fid}",
            "name": name,
            "label": "Faction",
            "summary": "",
            "facts": [],
            "attributes": {
                "faction_id": fid,
                "knesset_num": faction.get("KnessetNum"),
                "is_current": bool(faction.get("IsCurrent", False)),
                "start_date": _safe_str(faction.get("StartDate", "")),
                "finish_date": _safe_str(faction.get("FinishDate", "")),
                "camp": _faction_camp(name) or "",
                "source": "knesset_odata",
            },
            "created_at": NOW,
            "updated_at": NOW,
        }
        try:
            gs.add_node(node)
            count += 1
        except Exception as exc:
            log.warning("Failed to add faction %s: %s", name, exc)

    log.info("Imported %d Faction nodes", count)
    return count


# ---------------------------------------------------------------------------
# 4. Import Bills
# ---------------------------------------------------------------------------

def import_bills(gs: JSONStorage, bills_file: str) -> int:
    """Create Bill nodes from raw bills.json. Returns count."""
    if not os.path.exists(bills_file):
        log.warning("Bills file not found: %s", bills_file)
        return 0

    with open(bills_file, "r", encoding="utf-8") as f:
        bills = json.load(f)

    count = 0
    for bill in bills:
        bid = bill.get("BillID")
        name = _safe_str(bill.get("Name", ""))
        if not bid or not name:
            continue

        node = {
            "id": f"bill_{bid}",
            "name": name,
            "label": "Bill",
            "summary": "",
            "facts": [],
            "attributes": {
                "bill_id": bid,
                "knesset_num": bill.get("KnessetNum"),
                "sub_type": _safe_str(bill.get("SubTypeDesc", "")),
                "sub_type_id": bill.get("SubTypeID"),
                "status_id": bill.get("StatusID"),
                "committee_id": bill.get("CommitteeID"),
                "private_number": bill.get("PrivateNumber"),
                "source": "knesset_odata",
            },
            "created_at": NOW,
            "updated_at": NOW,
        }
        try:
            gs.add_node(node)
            count += 1
        except Exception as exc:
            log.warning("Failed to add bill %d: %s", bid, exc)

    log.info("Imported %d Bill nodes", count)
    return count


# ---------------------------------------------------------------------------
# 5. Import Relationships
# ---------------------------------------------------------------------------

def _load_positions(raw_dir: str) -> dict:
    """Load positions.json keyed by PersonID string."""
    path = os.path.join(raw_dir, "positions.json")
    if not os.path.exists(path):
        log.warning("Positions file not found: %s", path)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def import_relationships(
    gs: JSONStorage,
    entities: Dict[int, dict],
    raw_dir: str,
) -> Dict[str, int]:
    """
    Create edges:
      - MEMBER_OF: MK -> Faction (from positions, 25th Knesset)
      - CHAIRED / SAT_ON: MK -> Committee (from positions)
    Returns dict of relation -> count.
    """
    positions_data = _load_positions(raw_dir)
    counts: Dict[str, int] = {"MEMBER_OF": 0, "CHAIRED": 0, "SAT_ON": 0}
    existing_factions = {n["id"] for n in gs.list_nodes(label="Faction")}

    for pid, entity in entities.items():
        mk_id = f"mk_{pid}"
        # Check this MK node exists
        if gs.get_node(mk_id) is None:
            continue

        person_positions = positions_data.get(str(pid), [])
        # Also check entity's own positions list
        entity_positions = entity.get("properties", {}).get("positions", [])

        # --- MEMBER_OF from positions.json ---
        seen_factions: Set[str] = set()
        for pos in person_positions:
            faction_id_raw = pos.get("FactionID")
            if faction_id_raw is None:
                continue
            faction_node_id = f"faction_{faction_id_raw}"
            if faction_node_id in seen_factions:
                continue
            if faction_node_id not in existing_factions:
                continue
            seen_factions.add(faction_node_id)

            knesset_num = pos.get("KnessetNum")
            edge = {
                "id": _edge_id(),
                "source_id": mk_id,
                "target_id": faction_node_id,
                "relation": "MEMBER_OF",
                "weight": 1.0,
                "fact": f"MK {pid} member of faction {faction_id_raw} (Knesset {knesset_num})",
                "attributes": {
                    "knesset_num": knesset_num,
                    "start_date": _safe_str(pos.get("StartDate", "")),
                    "finish_date": _safe_str(pos.get("FinishDate", "")),
                    "is_current": bool(pos.get("IsCurrent", False)),
                },
                "created_at": NOW,
            }
            try:
                gs.add_edge(edge)
                counts["MEMBER_OF"] += 1
            except StorageError:
                pass  # missing node — skip silently

        # --- MEMBER_OF from entity positions (may have faction name but not ID) ---
        for pos in entity_positions:
            faction_name = _safe_str(pos.get("faction", ""))
            if not faction_name:
                continue
            # Try to find faction node by name
            faction_node = gs.get_node_by_name(faction_name)
            if faction_node is None:
                continue
            faction_node_id = faction_node["id"]
            if faction_node_id in seen_factions:
                continue
            seen_factions.add(faction_node_id)

            knesset_num = pos.get("knesset_num")
            edge = {
                "id": _edge_id(),
                "source_id": mk_id,
                "target_id": faction_node_id,
                "relation": "MEMBER_OF",
                "weight": 1.0,
                "fact": f"MK {pid} member of {faction_name} (Knesset {knesset_num})",
                "attributes": {
                    "knesset_num": knesset_num,
                    "start_date": _safe_str(pos.get("start_date", "")),
                    "end_date": _safe_str(pos.get("end_date", "")),
                    "is_current": bool(pos.get("is_current", False)),
                },
                "created_at": NOW,
            }
            try:
                gs.add_edge(edge)
                counts["MEMBER_OF"] += 1
            except StorageError:
                pass

        # --- CHAIRED / SAT_ON committees from positions.json ---
        seen_committees: Set[Tuple[str, Optional[int]]] = set()
        for pos in person_positions:
            committee_id = pos.get("CommitteeID")
            committee_name = _safe_str(pos.get("CommitteeName", ""))
            if not committee_id and not committee_name:
                continue

            # Create committee node on-the-fly if needed
            committee_node_id = f"committee_{committee_id}" if committee_id else f"committee_{hash(committee_name) & 0xFFFFFF}"
            dedup_key = (committee_node_id, pos.get("KnessetNum"))
            if dedup_key in seen_committees:
                continue
            seen_committees.add(dedup_key)

            # Ensure committee node exists
            if gs.get_node(committee_node_id) is None:
                gs.add_node({
                    "id": committee_node_id,
                    "name": committee_name or f"Committee {committee_id}",
                    "label": "Committee",
                    "summary": "",
                    "facts": [],
                    "attributes": {
                        "committee_id": committee_id,
                        "source": "knesset_odata",
                    },
                    "created_at": NOW,
                    "updated_at": NOW,
                })

            # Determine relation type from DutyDesc
            duty = _safe_str(pos.get("DutyDesc", "")).lower()
            if "יושב ראש" in duty or "chairman" in duty.lower():
                relation = "CHAIRED"
            else:
                relation = "SAT_ON"

            edge = {
                "id": _edge_id(),
                "source_id": mk_id,
                "target_id": committee_node_id,
                "relation": relation,
                "weight": 1.0,
                "fact": f"MK {pid} {relation.lower()} {committee_name}",
                "attributes": {
                    "knesset_num": pos.get("KnessetNum"),
                    "start_date": _safe_str(pos.get("StartDate", "")),
                    "finish_date": _safe_str(pos.get("FinishDate", "")),
                    "duty": _safe_str(pos.get("DutyDesc", "")),
                },
                "created_at": NOW,
            }
            try:
                gs.add_edge(edge)
                counts[relation] += 1
            except StorageError:
                pass

    log.info(
        "Imported relationships — MEMBER_OF: %d, CHAIRED: %d, SAT_ON: %d",
        counts["MEMBER_OF"], counts["CHAIRED"], counts["SAT_ON"],
    )
    return counts


# ---------------------------------------------------------------------------
# 6. Build coalition map
# ---------------------------------------------------------------------------

def build_coalition_map(gs: JSONStorage) -> int:
    """
    Tag each 25th Knesset faction as coalition or opposition via FACTION_COALITION edge.
    Returns count of edges created.
    """
    # Create the two camp nodes
    for camp_id, camp_name in [("camp_coalition", "קואליציה"), ("camp_opposition", "אופוזיציה")]:
        if gs.get_node(camp_id) is None:
            gs.add_node({
                "id": camp_id,
                "name": camp_name,
                "label": "PoliticalCamp",
                "summary": f"25th Knesset {camp_id.split('_')[1]}",
                "facts": [],
                "attributes": {"knesset_num": 25, "source": "manual"},
                "created_at": NOW,
                "updated_at": NOW,
            })

    factions = gs.list_nodes(label="Faction")
    count = 0
    for faction in factions:
        knesset_num = faction.get("attributes", {}).get("knesset_num")
        if knesset_num != 25:
            continue
        camp = _faction_camp(faction["name"])
        if camp is None:
            log.debug("No camp for faction: %s", faction["name"])
            continue

        target_id = f"camp_{camp}"
        edge = {
            "id": _edge_id(),
            "source_id": faction["id"],
            "target_id": target_id,
            "relation": "FACTION_COALITION",
            "weight": 1.0,
            "fact": f"{faction['name']} is in the {camp}",
            "attributes": {"knesset_num": 25},
            "created_at": NOW,
        }
        try:
            gs.add_edge(edge)
            count += 1
        except StorageError as exc:
            log.warning("Failed coalition edge for %s: %s", faction["name"], exc)

    log.info("Built coalition map: %d FACTION_COALITION edges", count)
    return count


# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Knesset data from RZMAPPER into MiroFish graph"
    )
    parser.add_argument(
        "--rzmapper-path",
        default=os.path.join(SCRIPT_DIR, "..", "..", "RZMAPPER"),
        help="Path to RZMAPPER project root (default: ../../RZMAPPER)",
    )
    parser.add_argument(
        "--graph-dir",
        default=os.path.join(BACKEND_DIR, "data", "graph", "knesset"),
        help="Path to graph storage directory (default: backend/data/graph/knesset)",
    )
    args = parser.parse_args()

    rzmapper = os.path.abspath(args.rzmapper_path)
    graph_dir = os.path.abspath(args.graph_dir)

    entities_dir = os.path.join(rzmapper, "data", "entities")
    raw_dir = os.path.join(rzmapper, "data", "raw", "knesset")
    factions_file = os.path.join(raw_dir, "factions.json")
    bills_file = os.path.join(raw_dir, "bills.json")

    # Validate paths
    for label, path in [("entities_dir", entities_dir), ("raw_dir", raw_dir)]:
        if not os.path.isdir(path):
            log.error("%s not found: %s", label, path)
            sys.exit(1)

    log.info("RZMAPPER path: %s", rzmapper)
    log.info("Graph storage: %s", graph_dir)

    # Initialize storage
    gs = JSONStorage(graph_dir)

    # Step 1: Load entities
    entities = load_rzmapper_entities(entities_dir)

    # Step 2: Import MKs
    mk_count = import_mks(gs, entities)

    # Step 3: Import Factions
    faction_count = import_factions(gs, factions_file)

    # Step 4: Import Bills
    bill_count = import_bills(gs, bills_file)

    # Step 5: Import Relationships
    rel_counts = import_relationships(gs, entities, raw_dir)

    # Step 6: Build coalition map
    coalition_count = build_coalition_map(gs)

    # Summary
    stats = gs.get_stats()
    log.info("=" * 60)
    log.info("IMPORT COMPLETE")
    log.info("=" * 60)
    log.info("  MKs imported:        %d", mk_count)
    log.info("  Factions imported:    %d", faction_count)
    log.info("  Bills imported:       %d", bill_count)
    log.info("  MEMBER_OF edges:      %d", rel_counts.get("MEMBER_OF", 0))
    log.info("  CHAIRED edges:        %d", rel_counts.get("CHAIRED", 0))
    log.info("  SAT_ON edges:         %d", rel_counts.get("SAT_ON", 0))
    log.info("  Coalition edges:      %d", coalition_count)
    log.info("  Total nodes:          %d", stats["node_count"])
    log.info("  Total edges:          %d", stats["edge_count"])
    log.info("=" * 60)

    gs.close()


if __name__ == "__main__":
    main()
