"""Knesset Data Daemon — continuous collection loop.

Manages a priority queue of data sources, running each collector
at configured intervals. Persists state in SQLite so it can resume
after restarts.

Usage:
    daemon = KnessetDataDaemon(graph_storage, pinecone_service)
    daemon.start()  # Runs forever in background thread
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ontology import COLLECTION_SOURCES
from .types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.daemon")


class KnessetDataDaemon:
    """Continuous data collection daemon for Knesset sources."""

    def __init__(
        self,
        graph_storage=None,
        pinecone_service=None,
        db_path: Optional[str] = None,
        data_dir: Optional[str] = None,
    ):
        self.graph_storage = graph_storage
        self.pinecone_service = pinecone_service
        self._data_dir = data_dir or os.path.join(
            os.path.dirname(__file__), "../../../data"
        )
        self._db_path = db_path or os.path.join(self._data_dir, "collection_state.db")
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._collectors: Dict[str, Any] = {}

        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # SQLite state management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist, seed sources."""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS collection_sources (
                    source_id TEXT PRIMARY KEY,
                    priority INTEGER DEFAULT 2,
                    last_collected_at TEXT,
                    next_collect_at TEXT,
                    collect_interval_seconds INTEGER DEFAULT 86400,
                    cursor_state TEXT,
                    error_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    total_items_collected INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS collection_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    items_new INTEGER DEFAULT 0,
                    items_updated INTEGER DEFAULT 0,
                    items_skipped INTEGER DEFAULT 0,
                    error TEXT,
                    duration_seconds REAL DEFAULT 0,
                    FOREIGN KEY (source_id) REFERENCES collection_sources(source_id)
                );

                CREATE INDEX IF NOT EXISTS idx_log_source
                    ON collection_log(source_id);
                CREATE INDEX IF NOT EXISTS idx_log_started
                    ON collection_log(started_at);
            """)

            # Seed sources from ontology if not present
            for source_id, config in COLLECTION_SOURCES.items():
                conn.execute("""
                    INSERT OR IGNORE INTO collection_sources
                        (source_id, priority, collect_interval_seconds, next_collect_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    source_id,
                    config["priority"],
                    config["interval_seconds"],
                    datetime.now(timezone.utc).isoformat(),
                ))
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def get_next_due_source(self) -> Optional[Dict[str, Any]]:
        """Get the highest-priority source that's due for collection."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT * FROM collection_sources
                WHERE enabled = 1
                    AND (next_collect_at IS NULL OR next_collect_at <= ?)
                ORDER BY priority ASC, last_collected_at ASC
                LIMIT 1
            """, (now,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_source_state(
        self,
        source_id: str,
        result: CollectionResult,
    ) -> None:
        """Update source state after a collection run."""
        now = datetime.now(timezone.utc)
        conn = self._get_conn()
        try:
            # Get interval for scheduling next run
            row = conn.execute(
                "SELECT collect_interval_seconds, total_items_collected, error_count "
                "FROM collection_sources WHERE source_id = ?",
                (source_id,)
            ).fetchone()

            if row is None:
                return

            interval = row["collect_interval_seconds"]
            total = row["total_items_collected"] + result.items_new + result.items_updated

            if result.success:
                from datetime import timedelta
                next_at = (now + timedelta(seconds=interval)).isoformat()
                conn.execute("""
                    UPDATE collection_sources SET
                        last_collected_at = ?,
                        next_collect_at = ?,
                        cursor_state = ?,
                        error_count = 0,
                        last_error = NULL,
                        total_items_collected = ?
                    WHERE source_id = ?
                """, (
                    now.isoformat(),
                    next_at,
                    json.dumps(result.new_cursor) if result.new_cursor else None,
                    total,
                    source_id,
                ))
            else:
                # Exponential backoff on errors
                err_count = row["error_count"] + 1
                backoff = min(interval, 300 * (2 ** min(err_count, 8)))
                from datetime import timedelta
                next_at = (now + timedelta(seconds=backoff)).isoformat()
                conn.execute("""
                    UPDATE collection_sources SET
                        last_collected_at = ?,
                        next_collect_at = ?,
                        error_count = ?,
                        last_error = ?,
                        total_items_collected = ?
                    WHERE source_id = ?
                """, (
                    now.isoformat(),
                    next_at,
                    err_count,
                    result.error,
                    total,
                    source_id,
                ))

            # Log the run
            conn.execute("""
                INSERT INTO collection_log
                    (source_id, started_at, finished_at, items_new,
                     items_updated, items_skipped, error, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_id,
                (now - __import__("datetime").timedelta(seconds=result.duration_seconds)).isoformat(),
                now.isoformat(),
                result.items_new,
                result.items_updated,
                result.items_skipped,
                result.error,
                result.duration_seconds,
            ))

            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Collector registry
    # ------------------------------------------------------------------

    def register_collector(self, source_id: str, collector) -> None:
        """Register a collector instance for a source."""
        self._collectors[source_id] = collector

    def _get_collector(self, source_id: str):
        """Get the collector for a source, auto-registering if possible."""
        if source_id in self._collectors:
            return self._collectors[source_id]

        # Try to auto-create from known collector classes
        collector = self._create_collector(source_id)
        if collector:
            self._collectors[source_id] = collector
        return collector

    def _create_collector(self, source_id: str):
        """Auto-create a collector from source_id."""
        try:
            if source_id == "rzmapper:sync":
                from .rzmapper_bridge import RZMapperBridge
                return _RZMapperSyncCollector(
                    bridge=RZMapperBridge(),
                    graph_storage=self.graph_storage,
                )
            elif source_id.startswith("obudget:"):
                from .collectors.obudget_collector import OBudgetCollector
                return OBudgetCollector(
                    sub_source=source_id.split(":")[1],
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "knesset:protocols":
                from .collectors.protocol_collector import ProtocolCollector
                return ProtocolCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "knesset:odata:members":
                from .collectors.knesset_member_collector import KnessetMemberCollector
                return KnessetMemberCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "knesset:odata:bills":
                from .collectors.knesset_bill_collector import KnessetBillCollector
                return KnessetBillCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "knesset:odata:votes":
                from .collectors.knesset_vote_collector import KnessetVoteCollector
                return KnessetVoteCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "knesset:odata:committees":
                from .collectors.knesset_committee_collector import KnessetCommitteeCollector
                return KnessetCommitteeCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "oknesset:api":
                from .collectors.oknesset_collector import OKnessetCollector
                return OKnessetCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "hasadna:pipelines":
                from .collectors.hasadna_collector import HasadnaCollector
                return HasadnaCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "datagov:datasets":
                from .collectors.datagov_collector import DataGovCollector
                return DataGovCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "guidestar:ngos":
                from .collectors.guidestar_collector import GuideStarCollector
                return GuideStarCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "kolzchut:laws":
                from .collectors.kolzchut_collector import KolZchutCollector
                return KolZchutCollector(
                    graph_storage=self.graph_storage,
                    pinecone_service=self.pinecone_service,
                )
            elif source_id == "knesset:research":
                # Research center doesn't have a public API — skip gracefully
                return None
        except ImportError as e:
            logger.warning("Collector not available for %s: %s", source_id, e)
        return None

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main collection loop — runs until stopped."""
        logger.info("Knesset Data Daemon started")
        cycle_count = 0

        while self._running:
            source = self.get_next_due_source()
            if source is None:
                # Nothing due — sleep and check again
                time.sleep(30)
                continue

            source_id = source["source_id"]
            collector = self._get_collector(source_id)

            if collector is None:
                logger.debug("No collector for %s, skipping", source_id)
                # Mark as collected so we don't busy-loop
                self.update_source_state(source_id, CollectionResult(
                    source_id=source_id,
                    error="No collector registered",
                ))
                continue

            # Parse cursor state
            cursor_state = None
            if source.get("cursor_state"):
                try:
                    cursor_state = json.loads(source["cursor_state"])
                except (json.JSONDecodeError, TypeError):
                    pass

            # Run collection with timeout (max 10 min per source)
            MAX_COLLECTOR_SECONDS = 600
            logger.info("Collecting: %s (priority=%d)", source_id, source["priority"])
            start = time.time()
            try:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(collector.collect_incremental, cursor_state)
                    try:
                        result = future.result(timeout=MAX_COLLECTOR_SECONDS)
                    except concurrent.futures.TimeoutError:
                        logger.warning("Collector %s timed out after %ds", source_id, MAX_COLLECTOR_SECONDS)
                        result = CollectionResult(
                            source_id=source_id,
                            error=f"Timed out after {MAX_COLLECTOR_SECONDS}s",
                            duration_seconds=time.time() - start,
                        )
                result.duration_seconds = time.time() - start
            except Exception as e:
                logger.exception("Collector %s failed: %s", source_id, e)
                result = CollectionResult(
                    source_id=source_id,
                    error=str(e),
                    duration_seconds=time.time() - start,
                )

            self.update_source_state(source_id, result)

            if result.success:
                logger.info(
                    "Collected %s: +%d new, %d updated, %d skipped (%.1fs)",
                    source_id, result.items_new, result.items_updated,
                    result.items_skipped, result.duration_seconds,
                )
            else:
                logger.warning(
                    "Collection failed for %s: %s (%.1fs)",
                    source_id, result.error, result.duration_seconds,
                )

            cycle_count += 1
            # Brief pause between sources
            time.sleep(2)

        logger.info("Knesset Data Daemon stopped after %d cycles", cycle_count)

    def start(self) -> None:
        """Start the daemon in a background thread."""
        if self._running:
            logger.warning("Daemon already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="knesset-data-daemon",
            daemon=True,
        )
        self._thread.start()
        logger.info("Knesset Data Daemon thread started")

    def stop(self) -> None:
        """Stop the daemon gracefully."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("Knesset Data Daemon stopped")

    def trigger_source(self, source_id: str) -> bool:
        """Force immediate collection for a source (set next_collect_at to now)."""
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            result = conn.execute(
                "UPDATE collection_sources SET next_collect_at = ? WHERE source_id = ?",
                (now, source_id)
            )
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Status & health
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get daemon status and all source states."""
        conn = self._get_conn()
        try:
            sources = [dict(r) for r in conn.execute(
                "SELECT * FROM collection_sources ORDER BY priority, source_id"
            ).fetchall()]

            recent_logs = [dict(r) for r in conn.execute(
                "SELECT * FROM collection_log ORDER BY finished_at DESC LIMIT 20"
            ).fetchall()]

            total_items = sum(s.get("total_items_collected", 0) for s in sources)
            active_errors = sum(1 for s in sources if s.get("error_count", 0) > 0)

            return {
                "running": self._running,
                "total_sources": len(sources),
                "active_errors": active_errors,
                "total_items_collected": total_items,
                "sources": sources,
                "recent_logs": recent_logs,
            }
        finally:
            conn.close()

    @property
    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# RZMAPPER sync collector adapter
# ---------------------------------------------------------------------------

class _RZMapperSyncCollector:
    """Wraps RZMapperBridge as a daemon-compatible collector."""

    def __init__(self, bridge, graph_storage=None):
        self._bridge = bridge
        self._graph_storage = graph_storage

    def collect_incremental(self, cursor_state=None) -> CollectionResult:
        """Sync RZMAPPER entities into MiroFish graph."""
        try:
            personas = self._bridge.sync_entities()
            # Optionally store into graph storage
            if self._graph_storage is not None:
                for p in personas:
                    try:
                        self._graph_storage.upsert_node(
                            node_id=p.agent_id,
                            label="MK",
                            name=p.name_he,
                            attributes=p.to_dict(),
                        )
                    except Exception:
                        pass

            return CollectionResult(
                source_id="rzmapper:sync",
                items_new=len(personas),
                items_updated=0,
                items_skipped=0,
                new_cursor={"last_sync": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as e:
            return CollectionResult(
                source_id="rzmapper:sync",
                error=str(e),
            )
