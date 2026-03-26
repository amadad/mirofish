"""Kol Zchut (כל זכות) law and rights data collector.

Collects law articles and legal references from Kol Zchut's
MediaWiki-based platform via its API.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .base_collector import BaseKnessetCollector
from ..types_extended import CollectionResult

logger = logging.getLogger("mirofish.knesset.collector.kolzchut")

KOLZCHUT_API_BASE = "https://www.kolzchut.org.il/w/api.php"

# Search terms for law-related content
LAW_SEARCH_TERMS = [
    "חוק",           # Law
    "תקנות",         # Regulations
    "צו",            # Order
    "פקודה",         # Ordinance
    "חוק יסוד",      # Basic Law
    "זכויות",        # Rights
]

# MediaWiki API limits
MW_SEARCH_LIMIT = 50
MW_PARSE_LIMIT = 10


class KolZchutCollector(BaseKnessetCollector):
    """Collects law and rights data from Kol Zchut (kolzchut.org.il).

    Uses the MediaWiki API to search for and retrieve law articles,
    rights information, and legal references. Stores results as Law nodes.
    """

    SOURCE_ID = "kolzchut:laws"
    RATE_LIMIT_SECONDS = 1.0  # Be polite to community wiki

    def get_source_id(self) -> str:
        return self.SOURCE_ID

    # ------------------------------------------------------------------
    # Main collection entry point
    # ------------------------------------------------------------------

    def collect_incremental(
        self,
        cursor_state: Optional[Dict[str, Any]] = None,
    ) -> CollectionResult:
        start = time.time()
        cursor_state = cursor_state or {}
        term_index = cursor_state.get("term_index", 0)
        offset = cursor_state.get("offset", 0)

        if term_index >= len(LAW_SEARCH_TERMS):
            # All terms processed — reset
            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=0,
                items_updated=0,
                new_cursor={"term_index": 0, "offset": 0},
                duration_seconds=time.time() - start,
            )

        try:
            search_term = LAW_SEARCH_TERMS[term_index]
            new_count = 0
            updated_count = 0

            # Search for articles
            results = self._search_articles(search_term, offset)
            if results is None:
                logger.warning(
                    "%s: API unavailable for term '%s'",
                    self.get_source_id(),
                    search_term,
                )
                return CollectionResult(
                    source_id=self.get_source_id(),
                    error=f"API unavailable for search term '{search_term}'",
                    new_cursor=cursor_state,
                    duration_seconds=time.time() - start,
                )

            if not results:
                # No more results for this term — move to next
                new_cursor = {"term_index": term_index + 1, "offset": 0}
                return CollectionResult(
                    source_id=self.get_source_id(),
                    items_new=0,
                    items_updated=0,
                    new_cursor=new_cursor,
                    duration_seconds=time.time() - start,
                )

            # Process each search result
            for article in results:
                title = article.get("title", "")
                if not title:
                    continue

                # Fetch article content
                content = self._fetch_article_content(title)

                was_new = self._upsert_law_node(article, content, search_term)
                if was_new:
                    new_count += 1
                else:
                    updated_count += 1

                # Extract and link related laws
                if content:
                    self._extract_law_links(title, content)

            # Pagination
            if len(results) >= MW_SEARCH_LIMIT:
                new_cursor = {
                    "term_index": term_index,
                    "offset": offset + MW_SEARCH_LIMIT,
                }
            else:
                new_cursor = {
                    "term_index": term_index + 1,
                    "offset": 0,
                }

            logger.info(
                "%s: term '%s' offset %d — %d articles (%d new, %d updated)",
                self.get_source_id(),
                search_term,
                offset,
                len(results),
                new_count,
                updated_count,
            )

            return CollectionResult(
                source_id=self.get_source_id(),
                items_new=new_count,
                items_updated=updated_count,
                new_cursor=new_cursor,
                duration_seconds=time.time() - start,
            )

        except Exception as exc:
            logger.exception("%s: collection failed", self.get_source_id())
            return CollectionResult(
                source_id=self.get_source_id(),
                error=str(exc),
                new_cursor=cursor_state,
                duration_seconds=time.time() - start,
            )

    # ------------------------------------------------------------------
    # MediaWiki API helpers
    # ------------------------------------------------------------------

    def _search_articles(
        self, query: str, offset: int = 0,
    ) -> Optional[List[Dict[str, Any]]]:
        """Search Kol Zchut for articles matching query.

        Returns list of search result dicts, or None on API failure.
        """
        data = self.fetch_json(
            KOLZCHUT_API_BASE,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "sroffset": str(offset),
                "srlimit": str(MW_SEARCH_LIMIT),
                "format": "json",
                "utf8": "1",
            },
        )
        if data is None:
            return None

        query_result = data.get("query", {})
        return query_result.get("search", [])

    def _fetch_article_content(self, title: str) -> Optional[str]:
        """Fetch parsed article content (plain text extract)."""
        data = self.fetch_json(
            KOLZCHUT_API_BASE,
            params={
                "action": "query",
                "titles": title,
                "prop": "extracts|categories|links",
                "exintro": "1",
                "explaintext": "1",
                "exlimit": "1",
                "cllimit": "20",
                "pllimit": "20",
                "format": "json",
                "utf8": "1",
            },
        )
        if data is None:
            return None

        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                return None
            return page_data.get("extract", "")

        return None

    def _fetch_article_categories(self, title: str) -> List[str]:
        """Fetch categories for an article."""
        data = self.fetch_json(
            KOLZCHUT_API_BASE,
            params={
                "action": "query",
                "titles": title,
                "prop": "categories",
                "cllimit": "50",
                "format": "json",
                "utf8": "1",
            },
        )
        if data is None:
            return []

        pages = data.get("query", {}).get("pages", {})
        categories: List[str] = []
        for page_data in pages.values():
            for cat in page_data.get("categories", []):
                cat_title = cat.get("title", "")
                # Strip "קטגוריה:" prefix
                if ":" in cat_title:
                    cat_title = cat_title.split(":", 1)[1]
                categories.append(cat_title)

        return categories

    # ------------------------------------------------------------------
    # Node / edge upsert
    # ------------------------------------------------------------------

    def _upsert_law_node(
        self,
        article: Dict[str, Any],
        content: Optional[str],
        search_term: str,
    ) -> bool:
        """Build and upsert a Law node from a search result. Returns True if new."""
        title = article.get("title", "")
        page_id = article.get("pageid", 0)
        if not title:
            return False

        # Sanitize title for use as node ID
        safe_title = title.replace(" ", "_").replace("/", "_")[:60]
        node_id = f"law_kz_{page_id or safe_title}"

        is_new = (
            self.graph_storage
            and self.graph_storage.get_node(node_id) is None
        )

        snippet = article.get("snippet", "")
        # Clean HTML from snippet
        import re
        clean_snippet = re.sub(r"<[^>]+>", "", snippet)

        node = {
            "id": node_id,
            "name": title,
            "label": "Law",
            "attributes": {
                "kolzchut_page_id": page_id,
                "search_term": search_term,
                "snippet": clean_snippet[:500],
                "word_count": article.get("wordcount", 0),
                "timestamp": article.get("timestamp", ""),
                "content_preview": (content or "")[:1000],
                "url": f"https://www.kolzchut.org.il/he/{title.replace(' ', '_')}",
            },
            "facts": [
                f"Law/rights article '{title}' from Kol Zchut (PageID={page_id})",
            ],
        }
        self.upsert_node(node)

        # Index for semantic search
        search_text = f"Law: {title}. {clean_snippet[:300]}"
        if content:
            search_text += f" {content[:200]}"

        self.index_in_pinecone(
            text=search_text,
            metadata={"id": node_id, "label": "Law", "name": title},
            namespace="knesset_laws",
        )

        return bool(is_new)

    def _extract_law_links(self, title: str, content: str) -> None:
        """Extract references to other laws and create REFERENCES edges.

        Parses the article content for common law reference patterns
        (e.g. "חוק X", "סעיף Y לחוק Z").
        """
        import re

        # Pattern: "חוק <law name>" references
        law_pattern = re.compile(r'חוק\s+([\u0590-\u05FF\s,\-"\']+?)(?:[,\.]|\s*\()')
        matches = law_pattern.findall(content)

        safe_source = title.replace(" ", "_").replace("/", "_")[:60]
        source_id = f"law_kz_{safe_source}"

        seen_targets: set[str] = set()
        for match in matches:
            law_name = match.strip().rstrip(",. ")
            if not law_name or len(law_name) < 3:
                continue
            if law_name == title:
                continue  # Skip self-references

            safe_target = law_name.replace(" ", "_").replace("/", "_")[:60]
            target_id = f"law_kz_{safe_target}"

            if target_id in seen_targets:
                continue
            seen_targets.add(target_id)

            # Ensure the referenced law exists as a stub node
            stub = {
                "id": target_id,
                "name": f"חוק {law_name}",
                "label": "Law",
                "attributes": {"stub": True},
                "facts": [],
            }
            self.upsert_node(stub)

            edge = {
                "source_id": source_id,
                "target_id": target_id,
                "relation": "REFERENCES",
                "attributes": {"context": f"Referenced in '{title}'"},
            }
            self.upsert_edge(edge)
