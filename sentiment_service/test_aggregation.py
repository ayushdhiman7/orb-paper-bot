from datetime import datetime, timedelta, timezone

import pytest

from aggregation import SentimentItem, aggregate_sentiment, normalize_text

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
POSITIVE = {"positive": 0.8, "neutral": 0.1, "negative": 0.1}
NEGATIVE = {"positive": 0.1, "neutral": 0.1, "negative": 0.8}


def item(item_id, *, source="news", text="Quarterly revenue beats expectations", published=None,
         fetched=None, candidates=("RELIANCE.NS",), probabilities=POSITIVE):
    return SentimentItem(
        provider="test-provider",
        item_id=item_id,
        source_type=source,
        text=text,
        published_at=published or NOW - timedelta(minutes=10),
        fetched_at=fetched or NOW - timedelta(minutes=5),
        symbol_candidates=candidates,
        probabilities=probabilities,
        model_id="test-model",
        model_revision="test-revision",
    )


def test_separates_news_and_social_scores():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        items=[
            item("n1", source="news", probabilities=POSITIVE),
            item("s1", source="social", text="This company looks terrible", probabilities=NEGATIVE),
        ],
    )
    assert result.news.status == "available"
    assert result.social.status == "available"
    assert result.news.score > 0
    assert result.social.score < 0
    assert result.combined_score == pytest.approx(0.0, abs=0.02)


def test_future_published_or_not_yet_fetched_item_is_excluded():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        items=[
            item("future-published", published=NOW + timedelta(seconds=1)),
            item("future-fetched", fetched=NOW + timedelta(seconds=1)),
        ],
    )
    assert result.news.score is None
    assert all(not d.accepted for d in result.decisions)
    assert all(d.reason == "future_or_not_yet_observed" for d in result.decisions)


def test_stale_items_are_excluded():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        lookback_minutes=30,
        items=[item("stale", published=NOW - timedelta(hours=1))],
    )
    assert result.news.status == "unavailable"
    assert result.decisions[0].reason == "outside_lookback"


def test_wrong_symbol_is_not_attributed():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        items=[item("wrong-symbol", candidates=("TCS.NS",))],
    )
    assert result.news.score is None
    assert result.decisions[0].reason == "symbol_not_matched"


def test_duplicate_reposts_do_not_count_twice():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        items=[
            item("original", text="Reliance reports record profits https://example.com/a"),
            item("repost", source="social", text="RELIANCE reports record profits https://example.com/b"),
        ],
    )
    assert result.news.item_count + result.social.item_count == 1
    assert sum(d.reason == "duplicate_text" for d in result.decisions) == 1


def test_unknown_model_labels_are_not_treated_as_neutral():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        items=[item("unknown", probabilities={"LABEL_0": 0.1, "LABEL_1": 0.9})],
    )
    assert result.news.score is None
    assert result.decisions[0].reason == "unknown_or_invalid_model_labels"
    assert "unknown_model_labels_excluded" in result.warnings


def test_naive_timestamps_are_rejected_per_item():
    result = aggregate_sentiment(
        symbol="RELIANCE.NS",
        signal_time=NOW,
        items=[item("naive", published=datetime(2026, 10, 27, 5, 0))],
    )
    assert result.news.score is None
    assert result.decisions[0].reason == "invalid_timestamp"


def test_normalization_removes_urls_and_duplicate_whitespace():
    assert normalize_text("Good  earnings https://x.com/a") == normalize_text("GOOD earnings https://y.com/b")


def test_signal_time_must_be_timezone_aware():
    with pytest.raises(ValueError):
        aggregate_sentiment(
            symbol="RELIANCE.NS",
            signal_time=datetime(2026, 10, 27, 6, 0),
            items=[],
        )


def test_item_cap_limits_source_influence():
    many = [
        item(f"news-{i}", text=f"Distinct article number {i} beats earnings", published=NOW - timedelta(minutes=i))
        for i in range(5)
    ]
    result = aggregate_sentiment(
        symbol="RELIANCE.NS", signal_time=NOW, items=many, max_items_per_source=2
    )
    assert result.news.item_count == 2
    assert "news_item_cap_applied" in result.warnings
    assert sum(d.reason == "source_item_cap" for d in result.decisions) == 3
