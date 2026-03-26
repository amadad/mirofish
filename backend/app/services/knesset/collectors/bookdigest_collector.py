"""Collector for BookDigest processed content.

Reads analysis/synthesis output from the BOOKDIGEST pipeline and converts
it into knowledge nodes that can be injected into Knesset agent simulations
as external context (Hebrew-language insights from podcast episodes).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.bookdigest")

DEFAULT_BOOKDIGEST_DIR = "C:/Users/markb/Documents/MyVault/MarkSpaceIt/BOOKDIGEST_NEW"
OUTPUT_SUBDIR = "O-output"
INSIGHT_CHAR_LIMIT = 500


class BookDigestCollector(BaseKnessetCollector):
    """Collects processed BookDigest episode insights for simulation injection."""

    SOURCE_ID = "bookdigest:episodes"

    def __init__(
        self,
        bookdigest_dir: Optional[str] = None,
        graph_storage=None,
        pinecone_service=None,
    ):
        super().__init__(graph_storage=graph_storage, pinecone_service=pinecone_service)
        self.bookdigest_dir = Path(
            bookdigest_dir
            or os.environ.get("BOOKDIGEST_DIR", DEFAULT_BOOKDIGEST_DIR)
        )
        self.output_dir = self.bookdigest_dir / OUTPUT_SUBDIR

    def get_source_id(self) -> str:
        return self.SOURCE_ID

    def collect_incremental(
        self, cursor_state: Optional[Dict[str, Any]] = None
    ) -> CollectionResult:
        """Scan O-output/ for episode dirs and ingest new episodes."""
        start = time.time()
        processed: set = set(cursor_state.get("processed_episodes", [])) if cursor_state else set()
        new, updated, skipped = 0, 0, 0

        if not self.output_dir.is_dir():
            logger.error("BookDigest output dir not found: %s", self.output_dir)
            return CollectionResult(
                source_id=self.SOURCE_ID, error=f"Dir not found: {self.output_dir}",
                success=False, duration_seconds=time.time() - start,
            )

        for ep_dir in sorted(self.output_dir.iterdir()):
            if not ep_dir.is_dir():
                continue
            episode_id = ep_dir.name
            if episode_id in processed:
                skipped += 1
                continue

            content = self._read_episode_content(ep_dir)
            if not content:
                skipped += 1
                continue

            node = {
                "id": f"bookdigest:{episode_id}",
                "label": "BookDigest",
                "name": episode_id,
                "attributes": {
                    "episode_id": episode_id,
                    "title": episode_id.replace("-", " ").title(),
                    "key_insights": content[:INSIGHT_CHAR_LIMIT],
                    "source_path": str(ep_dir),
                },
                "facts": [f"BookDigest episode {episode_id} analysis"],
            }
            self.upsert_node(node)
            processed.add(episode_id)
            new += 1
            logger.info("Ingested BookDigest episode: %s", episode_id)

        return CollectionResult(
            source_id=self.SOURCE_ID,
            items_new=new,
            items_updated=updated,
            items_skipped=skipped,
            new_cursor={"processed_episodes": sorted(processed)},
            duration_seconds=time.time() - start,
        )

    def get_episode_insights(self, episode_id: str) -> str:
        """Return synthesis text for a specific episode, formatted for agent prompts."""
        ep_dir = self.output_dir / episode_id
        if not ep_dir.is_dir():
            logger.warning("Episode dir not found: %s", episode_id)
            return ""
        content = self._read_episode_content(ep_dir)
        if not content:
            return ""
        return f"--- ידע חיצוני: {episode_id} ---\n{content}\n--- סוף ידע חיצוני ---"

    def list_episodes(self) -> List[Dict[str, Any]]:
        """Return list of available episodes with metadata."""
        if not self.output_dir.is_dir():
            return []
        episodes: List[Dict[str, Any]] = []
        for ep_dir in sorted(self.output_dir.iterdir()):
            if not ep_dir.is_dir():
                continue
            has_synthesis = (ep_dir / "analysis" / "book-synthesis.md").exists()
            has_unified = (ep_dir / "unified" / "book-complete.md").exists()
            episodes.append({
                "id": ep_dir.name,
                "title": ep_dir.name.replace("-", " ").title(),
                "has_synthesis": has_synthesis or has_unified,
            })
        return episodes

    @staticmethod
    def _read_episode_content(ep_dir: Path) -> Optional[str]:
        """Read best available content file from an episode directory."""
        candidates = [
            ep_dir / "unified" / "book-complete.md",
            ep_dir / "analysis" / "book-synthesis.md",
        ]
        for path in candidates:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError as e:
                    logger.warning("Failed to read %s: %s", path, e)
        return None
