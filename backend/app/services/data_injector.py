"""Real-time data injection for live simulations.

Fetches news/events from external sources and injects them into
the simulation feed so agents react to real-world events.

Sources:
  - RSS feeds (news sites, Twitter lists via RSS bridges)
  - Custom events (API push during simulation)
  - Scheduled events (pre-configured timeline)
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger("mirofish.data_injector")


@dataclass
class InjectionEvent:
    """A real-world event injected into the simulation."""
    source: str          # "rss", "api", "scheduled"
    title: str
    content: str
    url: str = ""
    published_at: str = ""
    category: str = ""   # "news", "market", "social", "politics"
    impact: str = "medium"  # "low", "medium", "high", "breaking"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_feed_text(self) -> str:
        """Format as a feed item agents can react to."""
        impact_prefix = {
            "breaking": "[BREAKING NEWS]",
            "high": "[IMPORTANT]",
            "medium": "[NEWS]",
            "low": "[UPDATE]",
        }
        prefix = impact_prefix.get(self.impact, "[NEWS]")
        return f"{prefix} {self.title}: {self.content[:300]}"

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "published_at": self.published_at,
            "category": self.category,
            "impact": self.impact,
            "metadata": self.metadata,
        }


@dataclass
class RSSFeedConfig:
    """Configuration for an RSS feed source."""
    url: str
    name: str
    category: str = "news"
    default_impact: str = "medium"
    poll_interval_seconds: int = 300  # 5 minutes
    max_items: int = 5


class RSSParser:
    """Parse RSS/Atom feeds into InjectionEvents."""

    USER_AGENT = "MiroFish/1.0 (Simulation Data Injector)"

    @classmethod
    def fetch_and_parse(cls, config: RSSFeedConfig) -> List[InjectionEvent]:
        """Fetch an RSS feed and return injection events."""
        try:
            req = Request(config.url, headers={"User-Agent": cls.USER_AGENT})
            with urlopen(req, timeout=10) as response:
                raw = response.read()
            return cls._parse_xml(raw, config)
        except (URLError, ET.ParseError, Exception) as e:
            logger.warning("Failed to fetch RSS %s: %s", config.name, e)
            return []

    @classmethod
    def _parse_xml(cls, raw: bytes, config: RSSFeedConfig) -> List[InjectionEvent]:
        """Parse RSS or Atom XML into events."""
        root = ET.fromstring(raw)
        events = []

        # Try RSS 2.0 format
        items = root.findall(".//item")
        if not items:
            # Try Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//atom:entry", ns)

        for item in items[:config.max_items]:
            title = cls._get_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])
            description = cls._get_text(item, [
                "description", "content:encoded",
                "{http://www.w3.org/2005/Atom}content",
                "{http://www.w3.org/2005/Atom}summary",
            ])
            link = cls._get_text(item, ["link", "{http://www.w3.org/2005/Atom}link"])
            pub_date = cls._get_text(item, [
                "pubDate", "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated",
            ])

            if not title:
                continue

            # Strip HTML tags from description
            clean_desc = re.sub(r'<[^>]+>', '', description or "")
            clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()

            events.append(InjectionEvent(
                source="rss",
                title=title.strip(),
                content=clean_desc[:500],
                url=link or "",
                published_at=pub_date or "",
                category=config.category,
                impact=config.default_impact,
                metadata={"feed_name": config.name, "feed_url": config.url},
            ))

        return events

    @staticmethod
    def _get_text(element: ET.Element, tag_names: list) -> str:
        """Try multiple tag names and return first match."""
        for tag in tag_names:
            el = element.find(tag)
            if el is not None:
                if el.text:
                    return el.text
                # Atom links use href attribute
                if el.get("href"):
                    return el.get("href", "")
        return ""


class DataInjector:
    """Manages real-time data injection into simulations.

    Usage:
        injector = DataInjector()
        injector.add_rss_feed("https://feeds.bbci.co.uk/news/rss.xml", "BBC News")
        injector.add_custom_event("Market crash announced", "S&P500 drops 5%", impact="breaking")

        # During simulation round:
        events = injector.get_pending_events()
        feed_text = injector.format_for_feed(events)
    """

    def __init__(self):
        self._rss_feeds: List[RSSFeedConfig] = []
        self._custom_events: List[InjectionEvent] = []
        self._scheduled_events: List[Dict] = []  # {round_num: int, event: InjectionEvent}
        self._fetched_events: List[InjectionEvent] = []
        self._last_fetch_time: Dict[str, float] = {}  # feed_url -> timestamp
        self._seen_titles: set = set()  # dedup

    def add_rss_feed(
        self,
        url: str,
        name: str,
        category: str = "news",
        default_impact: str = "medium",
        poll_interval: int = 300,
        max_items: int = 5,
    ) -> None:
        """Register an RSS feed as a data source."""
        self._rss_feeds.append(RSSFeedConfig(
            url=url,
            name=name,
            category=category,
            default_impact=default_impact,
            poll_interval_seconds=poll_interval,
            max_items=max_items,
        ))
        logger.info("Added RSS feed: %s (%s)", name, url)

    def add_custom_event(
        self,
        title: str,
        content: str,
        category: str = "news",
        impact: str = "medium",
        url: str = "",
        metadata: Optional[Dict] = None,
    ) -> InjectionEvent:
        """Inject a custom event into the simulation."""
        event = InjectionEvent(
            source="api",
            title=title,
            content=content,
            url=url,
            published_at=datetime.now(timezone.utc).isoformat(),
            category=category,
            impact=impact,
            metadata=metadata or {},
        )
        self._custom_events.append(event)
        logger.info("Custom event injected: %s [%s]", title, impact)
        return event

    def add_scheduled_event(
        self,
        round_num: int,
        title: str,
        content: str,
        category: str = "news",
        impact: str = "high",
    ) -> None:
        """Schedule an event to appear at a specific simulation round."""
        event = InjectionEvent(
            source="scheduled",
            title=title,
            content=content,
            published_at=datetime.now(timezone.utc).isoformat(),
            category=category,
            impact=impact,
        )
        self._scheduled_events.append({"round_num": round_num, "event": event})
        logger.info("Scheduled event for round %d: %s", round_num, title)

    def fetch_all_feeds(self) -> List[InjectionEvent]:
        """Fetch new items from all RSS feeds (respects poll intervals)."""
        new_events = []
        now = time.time()

        for feed in self._rss_feeds:
            last = self._last_fetch_time.get(feed.url, 0)
            if now - last < feed.poll_interval_seconds:
                continue

            events = RSSParser.fetch_and_parse(feed)
            self._last_fetch_time[feed.url] = now

            # Dedup by title
            for event in events:
                if event.title not in self._seen_titles:
                    self._seen_titles.add(event.title)
                    new_events.append(event)

        self._fetched_events.extend(new_events)
        return new_events

    def get_events_for_round(self, round_num: int, fetch_rss: bool = True) -> List[InjectionEvent]:
        """Get all pending events for a simulation round.

        Returns:
            Combined list of: new RSS items + custom events + scheduled events for this round
        """
        events = []

        # Fetch RSS if due
        if fetch_rss:
            events.extend(self.fetch_all_feeds())

        # Custom events (drain queue)
        events.extend(self._custom_events)
        self._custom_events = []

        # Scheduled events for this round
        remaining_scheduled = []
        for scheduled in self._scheduled_events:
            if scheduled["round_num"] <= round_num:
                events.append(scheduled["event"])
            else:
                remaining_scheduled.append(scheduled)
        self._scheduled_events = remaining_scheduled

        return events

    def format_for_feed(self, events: List[InjectionEvent], max_items: int = 5) -> str:
        """Format events as text suitable for agent feed context."""
        if not events:
            return ""

        lines = ["\n--- REAL-WORLD EVENTS ---"]
        for event in events[:max_items]:
            lines.append(event.to_feed_text())
        lines.append("--- END EVENTS ---\n")
        return "\n".join(lines)

    def get_all_history(self) -> List[dict]:
        """Get all injected events history."""
        return [e.to_dict() for e in self._fetched_events]

    @property
    def stats(self) -> dict:
        return {
            "rss_feeds": len(self._rss_feeds),
            "fetched_events": len(self._fetched_events),
            "pending_custom": len(self._custom_events),
            "pending_scheduled": len(self._scheduled_events),
            "seen_titles": len(self._seen_titles),
        }
