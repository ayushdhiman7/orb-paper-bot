"""Google News RSS adapter (no API key required).

Fetches public RSS results and normalizes entries for the sentiment pipeline.
It does not score text or create trading signals. Respect the feed provider's
terms, cache responses, and keep request volume modest.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Callable, Iterable

from aggregation import DEFAULT_SYMBOL_ALIASES

FEED_URL = "https://news.google.com/rss/search"
USER_AGENT = "orb-paper-bot/0.1 (paper-trading research)"
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\\s+")


@dataclass(frozen=True)
class NewsItem:
    provider: str
    item_id: str
    title: str
    text: str
    published_at: datetime
    fetched_at: datetime
    symbol_candidates: tuple[str, ...]
    url: str | None


def _parse_datetime(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _plain_text(value: str) -> str:
    return _SPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", value or ""))).strip()


def _aliases_for(symbol: str, aliases: dict[str, frozenset[str]]) -> tuple[str, ...]:
    canonical = symbol.strip().upper()
    names = aliases.get(canonical, frozenset({canonical}))
    # Search the company/ticker names individually to improve feed relevance.
    return tuple(sorted({canonical, *(name for name in names if name != canonical)}))


def _matched_symbols(text: str, symbols: Iterable[str], aliases: dict[str, frozenset[str]]) -> tuple[str, ...]:
    upper = text.upper()
    matched: list[str] = []
    for symbol in symbols:
        names = aliases.get(symbol.upper(), frozenset({symbol.upper()}))
        for name in names:
            # Use boundaries for ticker-like names; multi-word company names
            # remain literal phrases, reducing accidental substring matches.
            if name.upper() in upper:
                matched.append(symbol.upper())
                break
    return tuple(sorted(set(matched)))


def parse_rss(xml_text: str, *, fetched_at: datetime, symbols: Iterable[str],
              aliases: dict[str, frozenset[str]] | None = None) -> list[NewsItem]:
    """Parse RSS XML into normalized entries; timestamps must be timezone-aware."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    alias_map = aliases if aliases is not None else DEFAULT_SYMBOL_ALIASES
    normalized_symbols = tuple(dict.fromkeys(s.upper() for s in symbols))
    root = ET.fromstring(xml_text)
    results: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = _plain_text(node.findtext("title", default=""))
        description = _plain_text(node.findtext("description", default=""))
        published_raw = node.findtext("pubDate", default="")
        link = node.findtext("link", default="").strip() or None
        guid = node.findtext("guid", default="").strip()
        if not title or not published_raw:
            continue
        try:
            published_at = _parse_datetime(published_raw)
        except (TypeError, ValueError, OverflowError):
            continue
        text = title if not description else f"{title}. {description}"
        candidates = _matched_symbols(f"{title} {description}", normalized_symbols, alias_map)
        results.append(NewsItem(
            provider="google_news_rss",
            item_id=guid or link or f"{published_at.isoformat()}:{title}",
            title=title,
            text=text,
            published_at=published_at,
            fetched_at=fetched_at.astimezone(timezone.utc),
            symbol_candidates=candidates,
            url=link,
        ))
    return results


def fetch_google_news(
    symbols: Iterable[str],
    *,
    fetched_at: datetime | None = None,
    max_items_per_query: int = 20,
    timeout_seconds: float = 10.0,
    pause_seconds: float = 0.25,
    opener: Callable = urllib.request.urlopen,
    aliases: dict[str, frozenset[str]] | None = None,
) -> list[NewsItem]:
    """Fetch a small set of Google News RSS feeds without an API key.

    Use only a modest number of symbols per run and cache results. Network errors
    raise a clear exception so callers can log unavailable data, not fake neutral.
    """
    if max_items_per_query < 1:
        raise ValueError("max_items_per_query must be >= 1")
    if timeout_seconds <= 0 or pause_seconds < 0:
        raise ValueError("timeout_seconds must be > 0 and pause_seconds >= 0")
    now = fetched_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    alias_map = aliases if aliases is not None else DEFAULT_SYMBOL_ALIASES
    requested = tuple(dict.fromkeys(s.upper() for s in symbols))
    all_items: list[NewsItem] = []
    seen: set[str] = set()
    for index, symbol in enumerate(requested):
        if symbol not in alias_map:
            continue  # Require a reviewed alias map; do not guess company names.
        terms = _aliases_for(symbol, alias_map)
        query = " OR ".join(f'"{term}"' for term in terms)
        params = urllib.parse.urlencode({
            "q": query,
            "hl": "en-IN",
            "gl": "IN",
            "ceid": "IN:en",
        })
        request = urllib.request.Request(
            f"{FEED_URL}?{params}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
        )
        try:
            with opener(request, timeout=timeout_seconds) as response:
                payload = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Google News RSS request failed for {symbol}") from exc
        parsed = parse_rss(payload.decode("utf-8", errors="replace"),
                           fetched_at=now, symbols=[symbol], aliases=alias_map)
        for item in parsed[:max_items_per_query]:
            if item.item_id not in seen:
                seen.add(item.item_id)
                all_items.append(item)
        if index < len(requested) - 1 and pause_seconds:
            time.sleep(pause_seconds)
    return all_items
