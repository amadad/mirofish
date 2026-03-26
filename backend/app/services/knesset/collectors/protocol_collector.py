"""Protocol collector for Knesset debates and committee sessions.

Fetches דברי הכנסת (speeches and debates) from the Knesset OData API,
downloads protocol documents, parses speaker segments, and stores
each speech as a graph node with MENTIONED_IN edges to recognized MKs.

Data sources:
  - KNS_DocumentCommitteeSession — committee session documents
  - KNS_PlmSessionItem — plenum session items with protocol links
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.protocols")

# ---------------------------------------------------------------------------
# Regex patterns for splitting protocol text by speaker
# ---------------------------------------------------------------------------

# Matches "היו"ר שם המדבר:" — chairperson pattern
_CHAIR_PATTERN = re.compile(
    r'^(היו"ר\s+.+?):\s*',
    re.MULTILINE,
)

# Matches "שם המדבר:" — general speaker at line start
# Hebrew name: at least two words, letters/quotes/hyphens, followed by colon
_SPEAKER_PATTERN = re.compile(
    r'^([\u0590-\u05FF\u200F"\'־\-]+(?:\s+[\u0590-\u05FF\u200F"\'־\-]+)+)\s*:\s*',
    re.MULTILINE,
)

# Combined: find all speaker boundaries
_ALL_SPEAKERS_PATTERN = re.compile(
    r'^((?:היו"ר\s+)?[\u0590-\u05FF\u200F"\'־\-]+(?:\s+[\u0590-\u05FF\u200F"\'־\-]+)*)\s*:\s*',
    re.MULTILINE,
)

# Max content length stored per speech segment
_MAX_CONTENT_CHARS = 2000


class ProtocolCollector(BaseKnessetCollector):
    """Collects Knesset protocol records (speeches and debates).

    Fetches committee session documents and plenum session items from the
    Knesset OData API, downloads protocol text, splits by speaker, and
    stores each segment as a graph node.
    """

    SOURCE_ID = "knesset:protocols"

    # Protocol document download timeout is longer (large files)
    PROTOCOL_DOWNLOAD_TIMEOUT = 60

    def get_source_id(self) -> str:
        return self.SOURCE_ID

    def collect_incremental(
        self, cursor_state: Optional[Dict[str, Any]] = None
    ) -> CollectionResult:
        """Fetch protocol records newer than the last known session ID.

        Args:
            cursor_state: {"last_session_id": N, "knesset_num": 25}
                          None on first run (starts from session ID 0).

        Returns:
            CollectionResult with counts and updated cursor.
        """
        start_time = time.time()
        cursor = cursor_state or {"last_session_id": 0, "knesset_num": 25}
        last_session_id = cursor.get("last_session_id", 0)
        knesset_num = cursor.get("knesset_num", 25)

        items_new = 0
        items_updated = 0
        items_skipped = 0
        max_session_id = last_session_id

        try:
            # ----------------------------------------------------------
            # 1. Fetch committee session documents
            # ----------------------------------------------------------
            committee_items = self._fetch_committee_sessions(
                knesset_num, last_session_id
            )
            for session in committee_items:
                session_id = session.get("CommitteeSessionID", 0)
                if session_id > max_session_id:
                    max_session_id = session_id

                result = self._process_committee_session(session)
                if result == "new":
                    items_new += 1
                elif result == "updated":
                    items_updated += 1
                else:
                    items_skipped += 1

            # ----------------------------------------------------------
            # 2. Fetch plenum session items
            # ----------------------------------------------------------
            plenum_items = self._fetch_plenum_sessions(
                knesset_num, last_session_id
            )
            for session in plenum_items:
                plm_session_id = session.get("PlenumSessionID", 0)
                if plm_session_id > max_session_id:
                    max_session_id = plm_session_id

                result = self._process_plenum_session(session)
                if result == "new":
                    items_new += 1
                elif result == "updated":
                    items_updated += 1
                else:
                    items_skipped += 1

            new_cursor = {
                "last_session_id": max_session_id,
                "knesset_num": knesset_num,
            }

            duration = time.time() - start_time
            logger.info(
                "%s: collected %d new, %d updated, %d skipped in %.1fs",
                self.SOURCE_ID, items_new, items_updated, items_skipped, duration,
            )

            return CollectionResult(
                source_id=self.SOURCE_ID,
                items_new=items_new,
                items_updated=items_updated,
                items_skipped=items_skipped,
                new_cursor=new_cursor,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error("%s: collection failed: %s", self.SOURCE_ID, e, exc_info=True)
            return CollectionResult(
                source_id=self.SOURCE_ID,
                items_new=items_new,
                items_updated=items_updated,
                items_skipped=items_skipped,
                new_cursor={
                    "last_session_id": max_session_id,
                    "knesset_num": knesset_num,
                },
                error=str(e),
                duration_seconds=duration,
            )

    # ------------------------------------------------------------------
    # OData fetch helpers
    # ------------------------------------------------------------------

    def _fetch_committee_sessions(
        self, knesset_num: int, after_session_id: int
    ) -> List[Dict[str, Any]]:
        """Fetch committee sessions from OData.

        Uses KNS_CmtSessionItem which has the actual session data.
        KNS_DocumentCommitteeSession may not exist in all API versions.
        """
        # Try KNS_CmtSessionItem first (more reliable)
        for entity in ("KNS_CmtSessionItem", "KNS_DocumentCommitteeSession"):
            id_field = "CmtSessionItemID" if "CmtSession" in entity else "CommitteeSessionID"
            filter_expr = f"{id_field} gt {after_session_id}"
            params = {
                "$filter": filter_expr,
                "$orderby": f"{id_field} asc",
            }
            items = self.fetch_odata_all(
                entity,
                params=params,
                page_size=50,
                max_pages=20,
            )
            if items:
                # Normalize ID field name
                for item in items:
                    if "CommitteeSessionID" not in item:
                        item["CommitteeSessionID"] = item.get(id_field, 0)
                logger.info(
                    "%s: fetched %d committee sessions from %s (after ID %d)",
                    self.SOURCE_ID, len(items), entity, after_session_id,
                )
                return items
        logger.info(
            "%s: fetched 0 committee session documents (after ID %d)",
            self.SOURCE_ID, after_session_id,
        )
        return []

    def _fetch_plenum_sessions(
        self, knesset_num: int, after_session_id: int
    ) -> List[Dict[str, Any]]:
        """Fetch plenum session items from OData."""
        # Try KNS_PlenumSession first, then KNS_PlmSessionItem
        for entity in ("KNS_PlenumSession", "KNS_PlmSessionItem"):
            id_field = "PlenumSessionID" if "Plenum" in entity else "plmPlenumSessionID"
            filter_expr = f"{id_field} gt {after_session_id}"
            params = {
                "$filter": filter_expr,
                "$orderby": f"{id_field} asc",
            }
            items = self.fetch_odata_all(
                entity,
                params=params,
                page_size=50,
                max_pages=20,
            )
            if items:
                for item in items:
                    if "PlenumSessionID" not in item:
                        item["PlenumSessionID"] = item.get(id_field, 0)
                logger.info(
                    "%s: fetched %d plenum sessions from %s (after ID %d)",
                    self.SOURCE_ID, len(items), entity, after_session_id,
                )
                return items
        logger.info(
            "%s: fetched 0 plenum session items (after ID %d)",
            self.SOURCE_ID, after_session_id,
        )
        return []

    # ------------------------------------------------------------------
    # Session processors
    # ------------------------------------------------------------------

    def _process_committee_session(self, session: Dict[str, Any]) -> str:
        """Process a single committee session document.

        Returns: "new", "updated", or "skipped".
        """
        session_id = session.get("CommitteeSessionID", 0)
        date = self.parse_odata_date(session.get("StartDate")) or ""
        committee_name = session.get("CommitteeName", "")
        topic = session.get("Note", "") or session.get("Name", "")
        file_path = session.get("FilePath", "")

        node_id = f"protocol:committee:{session_id}"

        # Build base metadata node (even without protocol text)
        node = {
            "id": node_id,
            "label": "Protocol",
            "name": f"Committee Protocol {session_id}",
            "attributes": {
                "session_type": "committee",
                "session_id": str(session_id),
                "date": date,
                "committee": committee_name,
                "topic": topic[:500],
                "source": self.SOURCE_ID,
            },
            "facts": [
                f"Committee session {session_id} on {date}: {topic[:200]}",
            ],
        }

        # Attempt to download and parse protocol text
        segments = []
        if file_path:
            protocol_url = self._build_protocol_url(file_path)
            protocol_text = self._download_protocol(protocol_url)
            if protocol_text:
                segments = self._split_by_speaker(protocol_text)

        if segments:
            return self._store_speech_segments(
                segments, node, session_id, "committee", date, topic
            )
        else:
            # Store metadata-only node
            self.upsert_node(node)
            return "new"

    def _process_plenum_session(self, session: Dict[str, Any]) -> str:
        """Process a single plenum session item.

        Returns: "new", "updated", or "skipped".
        """
        session_id = session.get("PlenumSessionID", 0)
        date = self.parse_odata_date(session.get("StartDate")) or ""
        topic = session.get("Name", "") or session.get("ItemTitle", "")
        file_path = session.get("FilePath", "")

        node_id = f"protocol:plenum:{session_id}"

        node = {
            "id": node_id,
            "label": "Protocol",
            "name": f"Plenum Protocol {session_id}",
            "attributes": {
                "session_type": "plenum",
                "session_id": str(session_id),
                "date": date,
                "topic": topic[:500],
                "source": self.SOURCE_ID,
            },
            "facts": [
                f"Plenum session {session_id} on {date}: {topic[:200]}",
            ],
        }

        segments = []
        if file_path:
            protocol_url = self._build_protocol_url(file_path)
            protocol_text = self._download_protocol(protocol_url)
            if protocol_text:
                segments = self._split_by_speaker(protocol_text)

        if segments:
            return self._store_speech_segments(
                segments, node, session_id, "plenum", date, topic
            )
        else:
            self.upsert_node(node)
            return "new"

    # ------------------------------------------------------------------
    # Protocol download and parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _build_protocol_url(file_path: str) -> str:
        """Build full download URL from OData FilePath field.

        The FilePath may be a relative path or a full URL.
        """
        if file_path.startswith("http"):
            return file_path
        # Normalize backslashes
        file_path = file_path.replace("\\", "/")
        if file_path.startswith("/"):
            return f"https://knesset.gov.il{file_path}"
        return f"https://knesset.gov.il/{file_path}"

    def _download_protocol(self, url: str) -> Optional[str]:
        """Download protocol document text.

        Handles plain text and attempts basic HTML stripping.
        Word/RTF documents are fetched as-is; binary content is skipped.
        """
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=self.PROTOCOL_DOWNLOAD_TIMEOUT)
            if resp.status_code != 200:
                logger.debug(
                    "%s: protocol download HTTP %d for %s",
                    self.SOURCE_ID, resp.status_code, url,
                )
                return None

            content_type = resp.headers.get("Content-Type", "").lower()

            # Plain text or HTML — decode and return
            if "text/" in content_type or "html" in content_type:
                resp.encoding = resp.apparent_encoding or "utf-8"
                text = resp.text

                # Strip basic HTML tags if present
                if "<html" in text.lower() or "<body" in text.lower():
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()

                return text if len(text) > 50 else None

            # RTF — attempt to extract plain text between { }
            if "rtf" in content_type or url.lower().endswith(".rtf"):
                resp.encoding = resp.apparent_encoding or "utf-8"
                return self._extract_rtf_text(resp.text)

            # Binary doc/docx — not parseable without python-docx
            # Log and skip gracefully
            logger.debug(
                "%s: unsupported content type %s for %s",
                self.SOURCE_ID, content_type, url,
            )
            return None

        except Exception as e:
            logger.warning(
                "%s: protocol download error for %s: %s",
                self.SOURCE_ID, url, e,
            )
            return None

    @staticmethod
    def _extract_rtf_text(rtf_content: str) -> Optional[str]:
        """Basic RTF text extraction — strips control words and groups.

        This is a lightweight fallback; for full RTF parsing, use striprtf
        or similar library. Handles common Knesset RTF protocol files.
        """
        # Remove RTF control words: \word or \word123
        text = re.sub(r"\\[a-z]+\d*\s?", " ", rtf_content)
        # Remove braces
        text = text.replace("{", "").replace("}", "")
        # Remove hex escapes
        text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
        # Clean whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) > 50 else None

    # ------------------------------------------------------------------
    # Speaker segmentation
    # ------------------------------------------------------------------

    @staticmethod
    def _split_by_speaker(text: str) -> List[Tuple[str, str, str]]:
        """Split protocol text into speaker segments.

        Returns list of (speaker_name, speaker_role, content) tuples.

        Speaker roles:
          - "chair" for היו"ר patterns
          - "speaker" for all others
        """
        segments: List[Tuple[str, str, str]] = []
        matches = list(_ALL_SPEAKERS_PATTERN.finditer(text))

        if not matches:
            return segments

        for i, match in enumerate(matches):
            speaker_raw = match.group(1).strip()
            content_start = match.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[content_start:content_end].strip()

            if not content:
                continue

            # Determine role
            if speaker_raw.startswith('היו"ר'):
                role = "chair"
                # Extract name after היו"ר
                name = re.sub(r'^היו"ר\s+', "", speaker_raw).strip()
            else:
                role = "speaker"
                name = speaker_raw

            # Skip very short or garbage segments
            if len(content) < 10:
                continue

            segments.append((name, role, content))

        return segments

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _store_speech_segments(
        self,
        segments: List[Tuple[str, str, str]],
        parent_node: Dict[str, Any],
        session_id: int,
        session_type: str,
        date: str,
        topic: str,
    ) -> str:
        """Store each speech segment as a graph node and create edges.

        Returns "new" (we always treat protocol segments as new content).
        """
        # Store the parent session node first
        self.upsert_node(parent_node)

        for idx, (speaker_name, speaker_role, content) in enumerate(segments):
            segment_id = self._make_segment_id(session_id, session_type, idx)

            segment_node = {
                "id": segment_id,
                "label": "Protocol",
                "name": f"{speaker_name} — {session_type} {session_id}",
                "attributes": {
                    "session_type": session_type,
                    "session_id": str(session_id),
                    "date": date,
                    "speaker_name": speaker_name,
                    "speaker_role": speaker_role,
                    "topic": topic[:500],
                    "content_he": content[:_MAX_CONTENT_CHARS],
                    "segment_index": idx,
                    "source": self.SOURCE_ID,
                },
                "facts": [
                    f"{speaker_name} ({speaker_role}) spoke in {session_type} "
                    f"session {session_id} on {date} about: {topic[:100]}",
                ],
            }
            self.upsert_node(segment_node)

            # Link segment to parent session
            self.upsert_edge({
                "source_id": segment_id,
                "target_id": parent_node["id"],
                "relation": "PART_OF",
                "attributes": {"segment_index": idx},
            })

            # Create MENTIONED_IN edges for recognized MK names
            self._link_speaker_to_graph(speaker_name, segment_id)

            # Index speech content in Pinecone for semantic search
            self.index_in_pinecone(
                text=content[:4000],
                metadata={
                    "id": segment_id,
                    "speaker": speaker_name,
                    "role": speaker_role,
                    "session_type": session_type,
                    "date": date,
                    "topic": topic[:200],
                },
                namespace="knesset-protocols",
            )

        return "new"

    def _link_speaker_to_graph(self, speaker_name: str, segment_id: str) -> None:
        """Attempt to link a speaker name to an existing MK node in the graph.

        Searches graph storage for nodes matching the speaker name.
        Creates a MENTIONED_IN edge if found.
        """
        if self.graph_storage is None:
            return

        # Normalize name for lookup: strip quotes, extra whitespace
        normalized_name = re.sub(r'["\']', "", speaker_name).strip()
        if not normalized_name or len(normalized_name) < 3:
            return

        try:
            # Search by Hebrew name attribute
            mk_nodes = self.graph_storage.search_nodes(
                query=normalized_name,
                label="MK",
                limit=1,
            )
            if mk_nodes:
                mk_node = mk_nodes[0]
                self.upsert_edge({
                    "source_id": mk_node["id"],
                    "target_id": segment_id,
                    "relation": "MENTIONED_IN",
                    "attributes": {
                        "role": "speaker",
                        "source": self.SOURCE_ID,
                    },
                })
        except Exception as e:
            # Non-critical: graph search may not be available
            logger.debug(
                "%s: could not link speaker '%s': %s",
                self.SOURCE_ID, speaker_name, e,
            )

    @staticmethod
    def _make_segment_id(session_id: int, session_type: str, index: int) -> str:
        """Generate a deterministic ID for a speech segment."""
        raw = f"protocol:{session_type}:{session_id}:seg:{index}"
        suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
        return f"protocol:{session_type}:{session_id}:seg:{index}:{suffix}"
