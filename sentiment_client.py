"""Optional news-sentiment client. Results are context only and never gate entries."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
CACHE_SECONDS = 300
MAX_SYMBOLS_PER_SCAN = 10
SUPPORTED_NEWS_ALIASES = {
    "RELIANCE": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "INFY": "INFY.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
}


def _fetch_one(symbol: str) -> dict | None:
    base = symbol.upper().replace(".NS", "")
    service = os.getenv("SENTIMENT_SERVICE_URL", "").strip().rstrip("/")
    token = os.getenv("SENTIMENT_API_TOKEN", "").strip()
    if not service or base not in SUPPORTED_NEWS_ALIASES:
        return None
    now = time.time()
    with _LOCK:
        cached = _CACHE.get(base)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    body = json.dumps({
        "symbol": SUPPORTED_NEWS_ALIASES[base],
        "lookback_minutes": int(os.getenv("SENTIMENT_LOOKBACK_MINUTES", "180")),
        "max_items_per_query": int(os.getenv("SENTIMENT_MAX_ITEMS_PER_QUERY", "10")),
    }).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        service + "/research/news-sentiment", data=body, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("mode") != "shadow_research_only" or payload.get("trade_decision_changed") is not False:
            return None
        aggregation = payload.get("aggregation") or {}
        news = aggregation.get("news") or {}
        result = {
            "source": "google_news_rss",
            "news_score": news.get("score"),
            "news_item_count": int(news.get("item_count") or 0),
            "news_status": news.get("status", "unavailable"),
            "combined_score": aggregation.get("combined_score"),
            "social_status": (aggregation.get("social") or {}).get("status", "unavailable"),
            "model_id": payload.get("model_id"),
            "model_revision": payload.get("model_revision"),
            "collected_at": payload.get("collected_at"),
            "context_only": True,
        }
        with _LOCK:
            _CACHE[base] = (time.time(), result)
        return result
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
        return None


def fetch_candidate_sentiment(symbols, _now=None) -> dict[str, dict]:
    """Fetch cached/available news context for at most ten already-qualified candidates."""
    unique = sorted({str(symbol).upper().replace(".NS", "") for symbol in symbols})
    unique = [symbol for symbol in unique if symbol in SUPPORTED_NEWS_ALIASES][:MAX_SYMBOLS_PER_SCAN]
    results = {}
    if not unique:
        return results
    with ThreadPoolExecutor(max_workers=min(5, len(unique))) as pool:
        futures = {pool.submit(_fetch_one, symbol): symbol for symbol in unique}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result()
            except Exception:
                result = None
            if result is not None:
                results[symbol] = result
    return results
