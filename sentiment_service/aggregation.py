"""Time-safe, provider-neutral sentiment aggregation for paper-trading research.

This module consumes already-scored items. It does not fetch data, call a model,
or make trading decisions.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

SourceType = Literal["news", "social"]


@dataclass(frozen=True)
class SentimentItem:
    provider: str
    item_id: str
    source_type: SourceType
    text: str
    published_at: datetime
    fetched_at: datetime
    symbol_candidates: tuple[str, ...]
    probabilities: dict[str, float]
    model_id: str
    model_revision: str
    url: str | None = None


@dataclass(frozen=True)
class ItemDecision:
    item_id: str
    provider: str
    source_type: SourceType
    accepted: bool
    reason: str
    text_hash: str


@dataclass(frozen=True)
class SourceSummary:
    source_type: SourceType
    item_count: int
    score: float | None
    positive_share: float | None
    neutral_share: float | None
    negative_share: float | None
    average_confidence: float | None
    newest_item_at: datetime | None
    status: str


@dataclass(frozen=True)
class AggregationResult:
    symbol: str
    signal_time: datetime
    lookback_minutes: int
    news: SourceSummary
    social: SourceSummary
    combined_score: float | None
    decisions: tuple[ItemDecision, ...]
    warnings: tuple[str, ...]


# Explicit aliases only: avoid guessing that a company is mentioned from a
# generic word or ticker substring. Expand this map with a reviewed instrument list.
DEFAULT_SYMBOL_ALIASES: dict[str, frozenset[str]] = {
    "RELIANCE.NS": frozenset({"RELIANCE.NS", "RELIANCE", "RELIANCE INDUSTRIES"}),
    "TCS.NS": frozenset({"TCS.NS", "TCS", "TATA CONSULTANCY SERVICES"}),
    "INFY.NS": frozenset({"INFY.NS", "INFY", "INFOSYS"}),
    "HDFCBANK.NS": frozenset({"HDFCBANK.NS", "HDFCBANK", "HDFC BANK"}),
    "ICICIBANK.NS": frozenset({"ICICIBANK.NS", "ICICIBANK", "ICICI BANK"}),
}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def normalize_text(text: str) -> str:
    """Normalize text for exact/near-exact repost deduplication."""
    text = _URL_RE.sub(" ", text.lower())
    text = _NON_WORD_RE.sub(" ", text)
    return " ".join(text.split())


def text_digest(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _symbol_matches(symbol: str, candidates: Iterable[str], aliases: dict[str, frozenset[str]]) -> bool:
    expected = {symbol.upper(), *(x.upper() for x in aliases.get(symbol.upper(), frozenset()))}
    return any(str(candidate).strip().upper() in expected for candidate in candidates)


def _probability(probabilities: dict[str, float], *names: str) -> float | None:
    wanted = {name.lower() for name in names}
    for label, value in probabilities.items():
        cleaned = label.lower().replace("_", "").replace("-", "").strip()
        if cleaned in wanted:
            numeric = float(value)
            if 0.0 <= numeric <= 1.0:
                return numeric
            return None
    return None


def _class_probabilities(probabilities: dict[str, float]) -> tuple[float, float, float] | None:
    """Return positive, neutral, negative only when all three labels are known."""
    positive = _probability(probabilities, "positive", "bullish", "pos")
    neutral = _probability(probabilities, "neutral", "neu")
    negative = _probability(probabilities, "negative", "bearish", "neg")
    if positive is None or neutral is None or negative is None:
        return None
    total = positive + neutral + negative
    if total <= 0 or abs(total - 1.0) > 0.03:
        return None
    return positive / total, neutral / total, negative / total


def _empty_summary(source_type: SourceType, status: str) -> SourceSummary:
    return SourceSummary(source_type, 0, None, None, None, None, None, None, status)


def _summarize(source_type: SourceType, accepted: list[tuple[SentimentItem, tuple[float, float, float], float]]) -> SourceSummary:
    if not accepted:
        return _empty_summary(source_type, "unavailable")
    total_weight = sum(weight for _, _, weight in accepted)
    if total_weight <= 0:
        return _empty_summary(source_type, "unavailable")
    positive = sum(p[0] * w for _, p, w in accepted) / total_weight
    neutral = sum(p[1] * w for _, p, w in accepted) / total_weight
    negative = sum(p[2] * w for _, p, w in accepted) / total_weight
    confidence = sum(max(p) * w for _, p, w in accepted) / total_weight
    newest = max(item.published_at for item, _, _ in accepted)
    return SourceSummary(
        source_type=source_type,
        item_count=len(accepted),
        score=round(positive - negative, 6),
        positive_share=round(positive, 6),
        neutral_share=round(neutral, 6),
        negative_share=round(negative, 6),
        average_confidence=round(confidence, 6),
        newest_item_at=newest,
        status="available",
    )


def aggregate_sentiment(
    *,
    symbol: str,
    signal_time: datetime,
    items: Iterable[SentimentItem],
    lookback_minutes: int = 180,
    aliases: dict[str, frozenset[str]] | None = None,
    max_items_per_source: int = 20,
) -> AggregationResult:
    """Aggregate only fresh, symbol-matched items known by signal_time.

    Recency weighting is linear over the lookback interval. Each item is capped
    to weight <= 1.0, so a single high-confidence post cannot dominate by scale.
    Unknown model labels are excluded with a reason, not treated as neutral.
    """
    if lookback_minutes < 1:
        raise ValueError("lookback_minutes must be >= 1")
    if max_items_per_source < 1:
        raise ValueError("max_items_per_source must be >= 1")
    decision_at = _utc(signal_time, "signal_time")
    cutoff = decision_at - timedelta(minutes=lookback_minutes)
    alias_map = aliases if aliases is not None else DEFAULT_SYMBOL_ALIASES
    decisions: list[ItemDecision] = []
    candidates: list[tuple[SentimentItem, tuple[float, float, float], float]] = []
    seen_hashes: set[str] = set()
    warnings: set[str] = set()

    # Prefer the newest version when identical content appears in multiple feeds.
    def newest_first(item: SentimentItem) -> datetime:
        try:
            return _utc(item.published_at, "published_at")
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    ordered_items = sorted(items, key=newest_first, reverse=True)
    for item in ordered_items:
        digest = text_digest(item.text)
        try:
            published = _utc(item.published_at, "published_at")
            fetched = _utc(item.fetched_at, "fetched_at")
        except ValueError:
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "invalid_timestamp", digest))
            continue
        if item.source_type not in ("news", "social"):
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "unknown_source_type", digest))
            continue
        if published > decision_at or fetched > decision_at:
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "future_or_not_yet_observed", digest))
            warnings.add("future_or_late_observed_item_excluded")
            continue
        if published < cutoff:
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "outside_lookback", digest))
            continue
        if not _symbol_matches(symbol, item.symbol_candidates, alias_map):
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "symbol_not_matched", digest))
            continue
        if digest in seen_hashes:
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "duplicate_text", digest))
            continue
        classes = _class_probabilities(item.probabilities)
        if classes is None:
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "unknown_or_invalid_model_labels", digest))
            warnings.add("unknown_model_labels_excluded")
            continue
        seen_hashes.add(digest)
        age_fraction = max(0.0, (decision_at - published).total_seconds() / (lookback_minutes * 60))
        weight = min(1.0, max(0.0, (1.0 - age_fraction) * max(classes)))
        if weight <= 0:
            decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, False, "zero_weight", digest))
            continue
        candidates.append((item, classes, weight))
        decisions.append(ItemDecision(item.item_id, item.provider, item.source_type, True, "accepted", digest))

    # Bound influence by taking the newest unique observations per source.
    by_source: dict[str, list[tuple[SentimentItem, tuple[float, float, float], float]]] = {"news": [], "social": []}
    for entry in candidates:
        by_source[entry[0].source_type].append(entry)
    for source in by_source:
        by_source[source].sort(key=lambda entry: entry[0].published_at, reverse=True)
        if len(by_source[source]) > max_items_per_source:
            dropped = by_source[source][max_items_per_source:]
            by_source[source] = by_source[source][:max_items_per_source]
            dropped_ids = {entry[0].item_id for entry in dropped}
            decisions = [
                ItemDecision(d.item_id, d.provider, d.source_type, False, "source_item_cap", d.text_hash)
                if d.item_id in dropped_ids and d.accepted else d
                for d in decisions
            ]
            warnings.add(f"{source}_item_cap_applied")

    news = _summarize("news", by_source["news"])
    social = _summarize("social", by_source["social"])
    available_scores = [s.score for s in (news, social) if s.score is not None]
    combined = round(sum(available_scores) / len(available_scores), 6) if available_scores else None
    if news.status != "available":
        warnings.add("news_coverage_unavailable")
    if social.status != "available":
        warnings.add("social_coverage_unavailable")
    return AggregationResult(
        symbol=symbol.upper(),
        signal_time=decision_at,
        lookback_minutes=lookback_minutes,
        news=news,
        social=social,
        combined_score=combined,
        decisions=tuple(decisions),
        warnings=tuple(sorted(warnings)),
    )
