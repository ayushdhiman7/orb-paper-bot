"""Research-only Google News RSS -> FinTwitBERT -> aggregation pipeline.

This pipeline is intentionally separate from ORB entries and broker execution.
Historical backtests must use archived point-in-time data rather than querying today's RSS feed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from aggregation import AggregationResult, SentimentItem, aggregate_sentiment
from app import ModelRuntime, TextInput
from rss_news import NewsItem, fetch_google_news


def run_news_sentiment(
    *,
    symbol: str,
    signal_time: datetime | None = None,
    runtime: ModelRuntime,
    lookback_minutes: int = 180,
    max_items_per_query: int = 20,
    fetcher: Callable = fetch_google_news,
) -> tuple[AggregationResult, list[dict]]:
    """Fetch and score current RSS news for one reviewed NSE symbol.

    signal_time must be timezone-aware. Any article fetched after that time is
    excluded by aggregation. Returns aggregation plus auditable per-article
    metadata (not raw article text).
    """
    if signal_time is not None and (signal_time.tzinfo is None or signal_time.utcoffset() is None):
        raise ValueError("signal_time must be timezone-aware")
    if not runtime.ready:
        raise RuntimeError("Sentiment model is not available")
    fetched_at = datetime.now(timezone.utc)
    items: list[NewsItem] = fetcher(
        [symbol],
        fetched_at=fetched_at,
        max_items_per_query=max_items_per_query,
    )
    # For live shadow collection, set the decision timestamp after fetching.
    # For historical research, callers must supply an explicit signal timestamp.
    decision_time = signal_time or datetime.now(timezone.utc)
    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("signal_time must be timezone-aware")
    decision_time = decision_time.astimezone(timezone.utc)
    eligible = [
        item for item in items
        if item.published_at <= decision_time
        and item.fetched_at <= decision_time
    ]
    inputs = [TextInput(id=item.item_id[:128], text=item.text) for item in eligible]
    scored = runtime.score(inputs) if inputs else []
    score_by_id = {result.id: result for result in scored}
    normalized: list[SentimentItem] = []
    audit: list[dict] = []
    for item in items:
        result = score_by_id.get(item.item_id[:128])
        if result is None:
            audit.append({
                "item_id": item.item_id,
                "provider": item.provider,
                "published_at": item.published_at.isoformat(),
                "fetched_at": item.fetched_at.isoformat(),
                "symbol_candidates": list(item.symbol_candidates),
                "text_hash": hashlib.sha256(item.text.encode("utf-8")).hexdigest(),
                "scored": False,
                "reason": "not_available_by_signal_time",
                "url": item.url,
            })
            continue
        normalized.append(SentimentItem(
            provider=item.provider,
            item_id=item.item_id,
            source_type="news",
            text=item.text,
            published_at=item.published_at,
            fetched_at=item.fetched_at,
            symbol_candidates=item.symbol_candidates,
            probabilities=result.probabilities,
            model_id="StephanAkkerman/FinTwitBERT-sentiment",
            model_revision="configured",
            url=item.url,
        ))
        audit.append({
            "item_id": item.item_id,
            "provider": item.provider,
            "published_at": item.published_at.isoformat(),
            "fetched_at": item.fetched_at.isoformat(),
            "symbol_candidates": list(item.symbol_candidates),
            "text_hash": result.text_hash,
            "scored": True,
            "raw_label": result.raw_label,
            "label": result.label,
            "confidence": result.confidence,
            "url": item.url,
        })
    result = aggregate_sentiment(
        symbol=symbol,
        signal_time=decision_time,
        items=normalized,
        lookback_minutes=lookback_minutes,
    )
    return result, audit


def result_to_dict(result: AggregationResult) -> dict:
    """Convert immutable result dataclasses to JSON-friendly values."""
    def convert(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "__dataclass_fields__"):
            return {key: convert(val) for key, val in value.__dict__.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(val) for key, val in value.items()}
        return value
    return convert(result)
