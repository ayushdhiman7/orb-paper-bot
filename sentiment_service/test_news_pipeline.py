from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import TextInput
from news_pipeline import run_news_sentiment
from rss_news import NewsItem


class FakeRuntime:
    ready = True

    def score(self, inputs: list[TextInput]):
        return [
            SimpleNamespace(
                id=item.id,
                probabilities={"positive": 0.8, "neutral": 0.1, "negative": 0.1},
                text_hash="testhash",
                raw_label="positive",
                label="positive",
                confidence=0.8,
            )
            for item in inputs
        ]


def test_news_pipeline_scores_and_aggregates_items_known_before_signal():
    now = datetime.now(timezone.utc)
    def fetcher(symbols, *, fetched_at, max_items_per_query):
        return [NewsItem(
            provider="google_news_rss",
            item_id="news-1",
            title="Reliance Industries posts stronger results",
            text="Reliance Industries posts stronger results",
            published_at=now - timedelta(minutes=5),
            fetched_at=fetched_at,
            symbol_candidates=("RELIANCE.NS",),
            url="https://example.com/story",
        )]
    result, audit = run_news_sentiment(
        symbol="RELIANCE.NS",
        runtime=FakeRuntime(),
        fetcher=fetcher,
    )
    assert result.news.status == "available"
    assert result.news.item_count == 1
    assert result.news.score > 0
    assert audit[0]["scored"] is True
    assert audit[0]["provider"] == "google_news_rss"


def test_news_pipeline_rejects_naive_signal_time():
    try:
        run_news_sentiment(
            symbol="RELIANCE.NS",
            signal_time=datetime(2026, 10, 27),
            runtime=FakeRuntime(),
            fetcher=lambda *args, **kwargs: [],
        )
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("Expected timezone-aware timestamp validation")
