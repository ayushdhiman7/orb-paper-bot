from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from rss_news import fetch_google_news, parse_rss


NOW = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Reliance Industries shares rise after results</title>
    <link>https://example.com/reliance</link>
    <guid>reliance-1</guid>
    <pubDate>Tue, 27 Oct 2026 04:45:00 GMT</pubDate>
    <description><![CDATA[<b>Reliance Industries</b> reports stronger revenue.]]></description>
  </item>
  <item>
    <title>Market opens higher</title>
    <link>https://example.com/market</link>
    <pubDate>Tue, 27 Oct 2026 04:50:00 GMT</pubDate>
    <description>Broad market update</description>
  </item>
</channel></rss>"""


def test_parse_rss_normalizes_text_and_times_and_matches_symbols():
    items = parse_rss(XML, fetched_at=NOW, symbols=["RELIANCE.NS"])
    assert len(items) == 2
    item = items[0]
    assert item.provider == "google_news_rss"
    assert item.item_id == "reliance-1"
    assert item.published_at == datetime(2026, 10, 27, 4, 45, tzinfo=timezone.utc)
    assert item.fetched_at == NOW
    assert item.symbol_candidates == ("RELIANCE.NS",)
    assert "reports stronger revenue" in item.text
    assert items[1].symbol_candidates == ()


def test_parse_rejects_naive_fetched_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_rss(XML, fetched_at=datetime(2026, 10, 27), symbols=["RELIANCE.NS"])


def test_fetch_uses_mocked_opener_and_only_reviewed_symbols():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = XML.encode()
    opener = Mock(return_value=response)
    items = fetch_google_news(
        ["RELIANCE.NS", "UNKNOWN.NS"], fetched_at=NOW,
        pause_seconds=0, opener=opener,
    )
    assert len(items) == 2
    assert opener.call_count == 1
    request = opener.call_args.args[0]
    assert request.full_url.startswith("https://news.google.com/rss/search?")
    assert "Reliance" in request.full_url or "RELIANCE" in request.full_url


def test_fetch_validates_limits():
    with pytest.raises(ValueError, match="max_items_per_query"):
        fetch_google_news(["RELIANCE.NS"], max_items_per_query=0, opener=Mock())
