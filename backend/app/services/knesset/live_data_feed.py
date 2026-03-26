"""KnessetSim — Live data feed from Knesset API and Israeli news RSS.

Fetches real-time political events and formats them for injection into
simulation rounds.  Uses aiohttp for async HTTP, with feedparser for
RSS parsing (graceful fallback to stdlib XML if feedparser unavailable).

Usage:
    feed = LiveDataFeed()
    feed.setup_default_feeds()
    events = await feed.fetch_rss_news(keywords=["כנסת", "הצבעה"])
    prompt_text = feed.format_for_prompt(events)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mirofish.knesset.live_data_feed")

# Optional async HTTP — fall back to sync urllib if unavailable
try:
    import aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False
    logger.warning("aiohttp not installed — live feeds will use sync fallback")

# Optional feedparser — fall back to stdlib XML
try:
    import feedparser  # type: ignore[import-untyped]
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False
    logger.info("feedparser not installed — using stdlib XML for RSS parsing")

import re
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen
from urllib.error import URLError


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class KnessetEvent:
    """A real-time political event from Knesset API, RSS, or manual push."""

    event_id: str
    source: str  # "knesset_api" | "rss" | "manual"
    event_type: str  # "bill_tabled" | "vote_scheduled" | "committee_meeting" | "news" | "crisis"
    title_he: str
    content_he: str
    url: str = ""
    timestamp: str = ""
    impact: str = "medium"  # low | medium | high | breaking
    related_bill_id: Optional[str] = None
    related_mk_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "event_type": self.event_type,
            "title_he": self.title_he,
            "content_he": self.content_he,
            "url": self.url,
            "timestamp": self.timestamp,
            "impact": self.impact,
            "related_bill_id": self.related_bill_id,
            "related_mk_ids": self.related_mk_ids,
        }


@dataclass
class _RSSFeedEntry:
    """Internal RSS feed registration."""
    url: str
    name: str
    category: str = "news"


# ---------------------------------------------------------------------------
# Default Israeli news RSS feeds
# ---------------------------------------------------------------------------

_DEFAULT_RSS_FEEDS: List[dict] = [
    {
        "url": "https://www.ynet.co.il/Integration/StoryRss1.xml",
        "name": "Ynet",
        "category": "news",
    },
    {
        "url": "https://www.globes.co.il/webservice/rss/rssfeeder.asmx/FeederNode?iID=585",
        "name": "Globes",
        "category": "economy",
    },
    {
        "url": "https://www.calcalist.co.il/GeneralRSS/0,16335,L-8,00.xml",
        "name": "Calcalist",
        "category": "economy",
    },
    {
        "url": "https://rss.walla.co.il/feed/1",
        "name": "Walla News",
        "category": "news",
    },
    {
        "url": "https://www.maariv.co.il/Rss/RssFeedsMivzakimHadashot",
        "name": "Maariv",
        "category": "news",
    },
]

# Default political keywords for RSS filtering
_DEFAULT_KEYWORDS: List[str] = [
    "\u05db\u05e0\u05e1\u05ea",             # כנסת
    "\u05d4\u05e6\u05e2\u05ea \u05d7\u05d5\u05e7",  # הצעת חוק
    "\u05d4\u05e6\u05d1\u05e2\u05d4",       # הצבעה
    "\u05e7\u05d5\u05d0\u05dc\u05d9\u05e6\u05d9\u05d4",  # קואליציה
    "\u05d0\u05d5\u05e4\u05d5\u05d6\u05d9\u05e6\u05d9\u05d4",  # אופוזיציה
    "\u05d5\u05e2\u05d3\u05d4",             # ועדה
    "\u05de\u05dc\u05d9\u05d0\u05d4",       # מליאה
    "\u05e8\u05d0\u05e9 \u05d4\u05de\u05de\u05e9\u05dc\u05d4",  # ראש הממשלה
]


# ---------------------------------------------------------------------------
# LiveDataFeed
# ---------------------------------------------------------------------------

class LiveDataFeed:
    """Knesset API + News RSS integration for simulation event injection.

    Parameters
    ----------
    cache_dir : str
        Directory for caching fetched data (avoids redundant requests).
    """

    def __init__(self, cache_dir: str = "backend/data/knesset/feed_cache") -> None:
        self.rss_feeds: List[_RSSFeedEntry] = []
        self.knesset_api_base = "https://knesset.gov.il/Odata/ParliamentInfo.svc"
        self.cache_dir = cache_dir
        self._event_history: List[KnessetEvent] = []
        self._seen_ids: set = set()
        self._last_fetch: Dict[str, float] = {}  # source_key -> epoch

        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Feed management
    # ------------------------------------------------------------------

    def add_rss_feed(self, url: str, name: str, category: str = "news") -> None:
        """Register an RSS feed for polling."""
        self.rss_feeds.append(_RSSFeedEntry(url=url, name=name, category=category))
        logger.info("Added RSS feed: %s (%s)", name, url)

    def setup_default_feeds(self) -> None:
        """Register common Israeli news RSS feeds."""
        for feed_def in _DEFAULT_RSS_FEEDS:
            self.add_rss_feed(
                url=feed_def["url"],
                name=feed_def["name"],
                category=feed_def["category"],
            )
        logger.info("Set up %d default RSS feeds", len(_DEFAULT_RSS_FEEDS))

    # ------------------------------------------------------------------
    # Knesset OData API
    # ------------------------------------------------------------------

    async def fetch_knesset_updates(
        self, since_hours: int = 24,
    ) -> List[KnessetEvent]:
        """Query Knesset OData API for recent parliamentary changes.

        Fetches recent bills, upcoming votes, and committee meetings.

        Parameters
        ----------
        since_hours : int
            How far back to look (default 24 hours).

        Returns
        -------
        list[KnessetEvent]
        """
        events: List[KnessetEvent] = []

        # Respect poll interval (min 10 minutes)
        now = time.time()
        if now - self._last_fetch.get("knesset_api", 0) < 600:
            return events
        self._last_fetch["knesset_api"] = now

        # Fetch recent bills
        try:
            bills = await self._fetch_odata_bills(since_hours)
            events.extend(bills)
        except Exception as exc:
            logger.warning("Knesset bills fetch failed: %s", exc)

        # Fetch upcoming plenary sessions
        try:
            sessions = await self._fetch_odata_sessions(since_hours)
            events.extend(sessions)
        except Exception as exc:
            logger.warning("Knesset sessions fetch failed: %s", exc)

        # Dedup and store
        new_events = self._dedup_and_store(events)
        logger.info("Fetched %d Knesset API events (%d new)", len(events), len(new_events))
        return new_events

    async def _fetch_odata_bills(self, since_hours: int) -> List[KnessetEvent]:
        """Fetch recently updated bills from KNS_Bill."""
        url = (
            f"{self.knesset_api_base}/KNS_Bill()"
            f"?$orderby=LastUpdatedDate desc&$top=20"
            f"&$select=BillID,Name,SubTypeDescription,LastUpdatedDate,StatusID"
            f"&$format=json"
        )
        data = await self._http_get_json(url)
        if not data:
            return []

        events: List[KnessetEvent] = []
        for item in data.get("value", []):
            bill_name = item.get("Name", "")
            bill_id_val = item.get("BillID", "")
            sub_type = item.get("SubTypeDescription", "")
            updated = item.get("LastUpdatedDate", "")

            event = KnessetEvent(
                event_id=f"kns_bill_{bill_id_val}",
                source="knesset_api",
                event_type="bill_tabled",
                title_he=f"הצעת חוק: {bill_name}",
                content_he=f"סוג: {sub_type}. עודכן: {updated}",
                url=f"https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawBill.aspx?t=lawsuggestionssearch&lawitemid={bill_id_val}",
                timestamp=updated,
                impact="medium",
                related_bill_id=str(bill_id_val),
            )
            events.append(event)

        return events

    async def _fetch_odata_sessions(self, since_hours: int) -> List[KnessetEvent]:
        """Fetch upcoming plenary sessions from KNS_PlmSession."""
        url = (
            f"{self.knesset_api_base}/KNS_PlmSession()"
            f"?$orderby=StartDate desc&$top=10"
            f"&$select=PlenumSessionID,Number,StartDate,TypeDescription"
            f"&$format=json"
        )
        data = await self._http_get_json(url)
        if not data:
            return []

        events: List[KnessetEvent] = []
        for item in data.get("value", []):
            session_id = item.get("PlenumSessionID", "")
            number = item.get("Number", "")
            start_date = item.get("StartDate", "")
            type_desc = item.get("TypeDescription", "")

            event = KnessetEvent(
                event_id=f"kns_session_{session_id}",
                source="knesset_api",
                event_type="vote_scheduled",
                title_he=f"ישיבת מליאה #{number}",
                content_he=f"סוג: {type_desc}. תאריך: {start_date}",
                timestamp=start_date,
                impact="low",
            )
            events.append(event)

        return events

    # ------------------------------------------------------------------
    # RSS news
    # ------------------------------------------------------------------

    async def fetch_rss_news(
        self, keywords: Optional[List[str]] = None,
    ) -> List[KnessetEvent]:
        """Fetch and filter news from all registered RSS feeds.

        Parameters
        ----------
        keywords : list[str] | None
            Hebrew keywords to filter by.  Defaults to political terms.

        Returns
        -------
        list[KnessetEvent]
        """
        if keywords is None:
            keywords = _DEFAULT_KEYWORDS

        all_events: List[KnessetEvent] = []

        for feed_entry in self.rss_feeds:
            # Respect per-feed poll interval (5 min)
            now = time.time()
            if now - self._last_fetch.get(feed_entry.url, 0) < 300:
                continue
            self._last_fetch[feed_entry.url] = now

            try:
                raw_events = await self._parse_rss_feed(feed_entry)
            except Exception as exc:
                logger.warning("RSS fetch failed for %s: %s", feed_entry.name, exc)
                continue

            # Filter by keywords
            if keywords:
                filtered = []
                for event in raw_events:
                    text = f"{event.title_he} {event.content_he}".lower()
                    if any(kw in text for kw in keywords):
                        filtered.append(event)
                raw_events = filtered

            all_events.extend(raw_events)

        new_events = self._dedup_and_store(all_events)
        logger.info("Fetched %d RSS events (%d new, %d after keyword filter)",
                     len(all_events), len(new_events), len(new_events))
        return new_events

    async def _parse_rss_feed(self, feed_entry: _RSSFeedEntry) -> List[KnessetEvent]:
        """Parse a single RSS feed into KnessetEvents."""
        raw = await self._http_get_bytes(feed_entry.url)
        if not raw:
            return []

        events: List[KnessetEvent] = []

        if _HAS_FEEDPARSER:
            parsed = feedparser.parse(raw)
            for entry in parsed.entries[:15]:
                title = getattr(entry, "title", "") or ""
                summary = getattr(entry, "summary", "") or ""
                link = getattr(entry, "link", "") or ""
                published = getattr(entry, "published", "") or ""

                # Strip HTML
                clean_summary = re.sub(r"<[^>]+>", "", summary)
                clean_summary = re.sub(r"\s+", " ", clean_summary).strip()

                event_id = hashlib.md5(
                    f"{feed_entry.name}:{title}".encode("utf-8", errors="replace"),
                ).hexdigest()[:12]

                events.append(KnessetEvent(
                    event_id=event_id,
                    source="rss",
                    event_type="news",
                    title_he=title.strip(),
                    content_he=clean_summary[:500],
                    url=link,
                    timestamp=published,
                    impact="medium",
                ))
        else:
            # Stdlib XML fallback
            try:
                root = ET.fromstring(raw)
                items = root.findall(".//item")
                if not items:
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    items = root.findall(".//atom:entry", ns)

                for item in items[:15]:
                    title_el = item.find("title")
                    desc_el = item.find("description")
                    link_el = item.find("link")
                    pub_el = item.find("pubDate")

                    title = (title_el.text or "") if title_el is not None else ""
                    description = (desc_el.text or "") if desc_el is not None else ""
                    link = (link_el.text or "") if link_el is not None else ""
                    pub_date = (pub_el.text or "") if pub_el is not None else ""

                    clean_desc = re.sub(r"<[^>]+>", "", description)
                    clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

                    event_id = hashlib.md5(
                        f"{feed_entry.name}:{title}".encode("utf-8", errors="replace"),
                    ).hexdigest()[:12]

                    events.append(KnessetEvent(
                        event_id=event_id,
                        source="rss",
                        event_type="news",
                        title_he=title.strip(),
                        content_he=clean_desc[:500],
                        url=link,
                        timestamp=pub_date,
                        impact="medium",
                    ))
            except ET.ParseError as exc:
                logger.warning("XML parse error for %s: %s", feed_entry.name, exc)

        return events

    # ------------------------------------------------------------------
    # Manual event injection
    # ------------------------------------------------------------------

    def inject_manual_event(
        self,
        title_he: str,
        content_he: str,
        event_type: str = "manual",
        impact: str = "high",
    ) -> KnessetEvent:
        """Push a custom event into the feed.

        Parameters
        ----------
        title_he : str
            Hebrew title.
        content_he : str
            Hebrew description.
        event_type : str
            Event classification (default "manual").
        impact : str
            Impact level (default "high").

        Returns
        -------
        KnessetEvent
        """
        event = KnessetEvent(
            event_id=f"manual_{hashlib.md5(title_he.encode()).hexdigest()[:8]}",
            source="manual",
            event_type=event_type,
            title_he=title_he,
            content_he=content_he,
            timestamp=datetime.now(timezone.utc).isoformat(),
            impact=impact,
        )
        self._event_history.append(event)
        self._seen_ids.add(event.event_id)
        logger.info("Manual event injected: %s [%s]", title_he, impact)
        return event

    # ------------------------------------------------------------------
    # RZMAPPER social feed integration
    # ------------------------------------------------------------------

    async def fetch_rzmapper_social(
        self,
        mk_names: Optional[List[str]] = None,
        since_hours: int = 24,
    ) -> List[KnessetEvent]:
        """Fetch social media events from RZMAPPER's Telegram/Twitter data.

        Parameters
        ----------
        mk_names : list[str] | None
            MK names to filter for. If None, fetches all political content.
        since_hours : int
            How far back to look.

        Returns
        -------
        list[KnessetEvent]
        """
        events: List[KnessetEvent] = []

        # Respect poll interval (5 min)
        now = time.time()
        if now - self._last_fetch.get("rzmapper_social", 0) < 300:
            return events
        self._last_fetch["rzmapper_social"] = now

        try:
            from .rzmapper_bridge import RZMapperBridge
            bridge = RZMapperBridge()
            social_text = bridge.get_social_feed(
                mk_ids=mk_names or [],
                since_hours=since_hours,
            )
            if social_text:
                # Split social text into individual events (each line is a message)
                for i, line in enumerate(social_text.strip().split("\n")):
                    line = line.strip()
                    if not line or line.startswith("---"):
                        continue
                    event_id = hashlib.md5(
                        f"rzmapper_social_{i}_{line[:50]}".encode("utf-8", errors="replace"),
                    ).hexdigest()[:12]
                    events.append(KnessetEvent(
                        event_id=event_id,
                        source="rzmapper_social",
                        event_type="social_media",
                        title_he="רשתות חברתיות",
                        content_he=line[:500],
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        impact="medium",
                    ))
        except Exception as exc:
            logger.warning("RZMAPPER social feed failed: %s", exc)

        new_events = self._dedup_and_store(events)
        logger.info("Fetched %d RZMAPPER social events (%d new)", len(events), len(new_events))
        return new_events

    # ------------------------------------------------------------------
    # Round-level event selection
    # ------------------------------------------------------------------

    def get_events_for_round(
        self,
        round_num: int,
        max_events: int = 3,
    ) -> List[KnessetEvent]:
        """Select the most relevant events for a simulation round.

        Prioritises by: impact level, recency, and relevance to active bills.

        Parameters
        ----------
        round_num : int
            Current simulation round (used for logging).
        max_events : int
            Maximum events to return.

        Returns
        -------
        list[KnessetEvent]
        """
        impact_order = {"breaking": 0, "high": 1, "medium": 2, "low": 3}

        # Sort by impact (breaking first), then by recency (newest first)
        sorted_events = sorted(
            self._event_history,
            key=lambda e: (impact_order.get(e.impact, 9), -(hash(e.timestamp) % 10**8)),
        )

        selected = sorted_events[:max_events]
        logger.debug("Round %d: selected %d events from %d total",
                      round_num, len(selected), len(self._event_history))
        return selected

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def format_for_prompt(self, events: List[KnessetEvent]) -> str:
        """Format events as Hebrew text suitable for agent prompts.

        Parameters
        ----------
        events : list[KnessetEvent]
            Events to format.

        Returns
        -------
        str
            Formatted Hebrew text block.
        """
        if not events:
            return ""

        impact_prefix = {
            "breaking": "\u05d7\u05d3\u05e9\u05d5\u05ea \u05d3\u05d7\u05d5\u05e4\u05d5\u05ea",  # חדשות דחופות
            "high": "\u05d7\u05e9\u05d5\u05d1",  # חשוב
            "medium": "\u05d7\u05d3\u05e9\u05d5\u05ea",  # חדשות
            "low": "\u05e2\u05d3\u05db\u05d5\u05df",  # עדכון
        }

        lines = ["--- \u05d0\u05d9\u05e8\u05d5\u05e2\u05d9\u05dd \u05d0\u05d7\u05e8\u05d5\u05e0\u05d9\u05dd ---"]  # אירועים אחרונים
        for event in events:
            prefix = impact_prefix.get(event.impact, "\u05d7\u05d3\u05e9\u05d5\u05ea")
            lines.append(f"[{prefix}] {event.title_he}: {event.content_he[:200]}")
        lines.append("--- \u05e1\u05d5\u05e3 \u05d0\u05d9\u05e8\u05d5\u05e2\u05d9\u05dd ---")  # סוף אירועים

        return "\n".join(lines)

    # Alias for KnessetLoop compatibility
    format_for_feed = format_for_prompt

    def inject_event(self, event: KnessetEvent) -> None:
        """Manually inject a political event into the feed."""
        if event.event_id not in self._seen_ids:
            self._event_history.append(event)
            self._seen_ids.add(event.event_id)
            logger.info("Injected event: %s", event.title_he)

    def get_recent_events(self, limit: int = 20) -> List[KnessetEvent]:
        """Get the most recent events from history."""
        return list(reversed(self._event_history[-limit:]))

    # ------------------------------------------------------------------
    # DataInjector compatibility
    # ------------------------------------------------------------------

    def to_data_injector_events(self, events: List[KnessetEvent]) -> list:
        """Convert KnessetEvents to MiroFish DataInjector InjectionEvent dicts.

        For compatibility with the existing FastAgentLoop / DataInjector.

        Parameters
        ----------
        events : list[KnessetEvent]

        Returns
        -------
        list[dict]
            Each dict matches the InjectionEvent.to_dict() schema from
            ``backend.app.services.data_injector``.
        """
        result: List[dict] = []
        for event in events:
            result.append({
                "source": event.source,
                "title": event.title_he,
                "content": event.content_he,
                "url": event.url,
                "published_at": event.timestamp,
                "category": event.event_type,
                "impact": event.impact,
                "metadata": {
                    "knesset_event_id": event.event_id,
                    "related_bill_id": event.related_bill_id,
                    "related_mk_ids": event.related_mk_ids,
                },
            })
        return result

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _http_get_json(self, url: str) -> Optional[dict]:
        """Fetch JSON from a URL (async with aiohttp, sync fallback)."""
        if _HAS_AIOHTTP:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            return await resp.json(content_type=None)
                        logger.warning("HTTP %d from %s", resp.status, url)
            except Exception as exc:
                logger.warning("aiohttp GET failed for %s: %s", url, exc)
            return None

        # Sync fallback
        try:
            req = Request(url, headers={"User-Agent": "MiroFish-KnessetSim/1.0"})
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (URLError, json.JSONDecodeError) as exc:
            logger.warning("sync GET failed for %s: %s", url, exc)
            return None

    async def _http_get_bytes(self, url: str) -> Optional[bytes]:
        """Fetch raw bytes from a URL (async with aiohttp, sync fallback)."""
        if _HAS_AIOHTTP:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            return await resp.read()
                        logger.warning("HTTP %d from %s", resp.status, url)
            except Exception as exc:
                logger.warning("aiohttp GET failed for %s: %s", url, exc)
            return None

        # Sync fallback
        try:
            req = Request(url, headers={"User-Agent": "MiroFish-KnessetSim/1.0"})
            with urlopen(req, timeout=15) as resp:
                return resp.read()
        except URLError as exc:
            logger.warning("sync GET failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dedup_and_store(self, events: List[KnessetEvent]) -> List[KnessetEvent]:
        """Deduplicate events by event_id and append new ones to history."""
        new_events: List[KnessetEvent] = []
        for event in events:
            if event.event_id not in self._seen_ids:
                self._seen_ids.add(event.event_id)
                self._event_history.append(event)
                new_events.append(event)
        return new_events

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def save_cache(self) -> None:
        """Persist event history to disk."""
        cache_path = os.path.join(self.cache_dir, "event_history.json")
        try:
            data = [e.to_dict() for e in self._event_history]
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("Saved %d events to cache", len(data))
        except Exception as exc:
            logger.warning("Cache save failed: %s", exc)

    def load_cache(self) -> int:
        """Load event history from disk. Returns count of loaded events."""
        cache_path = os.path.join(self.cache_dir, "event_history.json")
        if not os.path.exists(cache_path):
            return 0
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                event = KnessetEvent(
                    event_id=item["event_id"],
                    source=item["source"],
                    event_type=item["event_type"],
                    title_he=item["title_he"],
                    content_he=item["content_he"],
                    url=item.get("url", ""),
                    timestamp=item.get("timestamp", ""),
                    impact=item.get("impact", "medium"),
                    related_bill_id=item.get("related_bill_id"),
                    related_mk_ids=item.get("related_mk_ids", []),
                )
                if event.event_id not in self._seen_ids:
                    self._seen_ids.add(event.event_id)
                    self._event_history.append(event)
            logger.info("Loaded %d events from cache", len(data))
            return len(data)
        except Exception as exc:
            logger.warning("Cache load failed: %s", exc)
            return 0

    @property
    def stats(self) -> dict:
        """Return feed statistics."""
        return {
            "rss_feeds_registered": len(self.rss_feeds),
            "total_events": len(self._event_history),
            "unique_event_ids": len(self._seen_ids),
            "sources": {
                source: sum(1 for e in self._event_history if e.source == source)
                for source in {"knesset_api", "rss", "manual", "rzmapper_social"}
            },
        }
