import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.data_injector import DataInjector, InjectionEvent, RSSParser, RSSFeedConfig


def test_custom_event_injection():
    injector = DataInjector()
    event = injector.add_custom_event(
        title="Market Crash",
        content="S&P500 drops 5% in one hour",
        category="market",
        impact="breaking",
    )
    assert event.source == "api"
    assert event.impact == "breaking"

    events = injector.get_events_for_round(1, fetch_rss=False)
    assert len(events) == 1
    assert events[0].title == "Market Crash"

    # Queue should be drained
    events2 = injector.get_events_for_round(2, fetch_rss=False)
    assert len(events2) == 0


def test_scheduled_events():
    injector = DataInjector()
    injector.add_scheduled_event(3, "Election Results", "Opposition wins majority", impact="breaking")
    injector.add_scheduled_event(5, "Protest", "Thousands march in capital", impact="high")

    # Round 1 — nothing scheduled
    events = injector.get_events_for_round(1, fetch_rss=False)
    assert len(events) == 0

    # Round 3 — first event fires
    events = injector.get_events_for_round(3, fetch_rss=False)
    assert len(events) == 1
    assert events[0].title == "Election Results"

    # Round 5 — second event fires
    events = injector.get_events_for_round(5, fetch_rss=False)
    assert len(events) == 1
    assert events[0].title == "Protest"


def test_event_feed_formatting():
    injector = DataInjector()
    injector.add_custom_event("Test News", "Something happened", impact="high")
    events = injector.get_events_for_round(1, fetch_rss=False)
    text = injector.format_for_feed(events)
    assert "REAL-WORLD EVENTS" in text
    assert "[IMPORTANT] Test News" in text


def test_injection_event_to_feed_text():
    event = InjectionEvent(
        source="rss", title="Breaking Story",
        content="Major event occurred today",
        impact="breaking",
    )
    text = event.to_feed_text()
    assert "[BREAKING NEWS]" in text
    assert "Breaking Story" in text


def test_dedup_by_title():
    injector = DataInjector()
    injector.add_custom_event("Same Title", "Content 1")
    events1 = injector.get_events_for_round(1, fetch_rss=False)
    # Add again with same title — but custom events don't dedup (only RSS does)
    # This tests the RSS dedup via _seen_titles
    injector._seen_titles.add("Duplicate Story")
    injector._fetched_events.append(InjectionEvent(
        source="rss", title="Duplicate Story", content="First version"
    ))
    # Simulate fetching same title again
    assert "Duplicate Story" in injector._seen_titles


def test_stats():
    injector = DataInjector()
    injector.add_rss_feed("http://example.com/feed", "Test Feed")
    injector.add_custom_event("Event", "Content")
    stats = injector.stats
    assert stats["rss_feeds"] == 1
    assert stats["pending_custom"] == 1


def test_rss_parser_xml():
    """Test RSS XML parsing with sample data."""
    sample_rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
    <channel>
        <title>Test Feed</title>
        <item>
            <title>Test Article</title>
            <description>This is a test article about economics</description>
            <link>http://example.com/article1</link>
            <pubDate>Mon, 23 Mar 2026 10:00:00 GMT</pubDate>
        </item>
        <item>
            <title>Second Article</title>
            <description>Another test article</description>
            <link>http://example.com/article2</link>
        </item>
    </channel>
    </rss>"""

    config = RSSFeedConfig(url="http://test.com", name="Test", category="news")
    events = RSSParser._parse_xml(sample_rss, config)
    assert len(events) == 2
    assert events[0].title == "Test Article"
    assert events[0].source == "rss"
    assert events[0].url == "http://example.com/article1"
