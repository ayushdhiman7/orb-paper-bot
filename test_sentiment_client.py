import sentiment_client


def test_sentiment_client_limits_to_supported_candidates(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sentiment_client, "_fetch_one",
        lambda symbol: calls.append(symbol) or {"news_score": 0.4, "context_only": True},
    )
    result = sentiment_client.fetch_candidate_sentiment(
        ["RELIANCE", "TCS", "UNKNOWN", "INFY", "HDFCBANK", "ICICIBANK", "EXTRA"]
    )
    assert set(result) == {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"}
    assert len(calls) == 5
    assert all(item["context_only"] for item in result.values())


def test_sentiment_client_returns_empty_for_unsupported_universe():
    assert sentiment_client.fetch_candidate_sentiment(["UNKNOWN", "NOTLISTED"]) == {}


def test_sentiment_client_preserves_news_and_social_scores(monkeypatch):
    import json
    import sentiment_client

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return json.dumps({
                "mode": "shadow_research_only",
                "trade_decision_changed": False,
                "model_id": "FinTwitBERT",
                "model_revision": "test",
                "collected_at": "2026-11-04T10:00:00+00:00",
                "aggregation": {
                    "news": {"score": 0.4, "item_count": 3, "status": "available"},
                    "social": {"score": -0.2, "item_count": 2, "status": "available"},
                    "combined_score": 0.1,
                },
            }).encode()

    sentiment_client._CACHE.clear()
    monkeypatch.setenv("SENTIMENT_SERVICE_URL", "https://sentiment.example")
    monkeypatch.setattr(sentiment_client.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    result = sentiment_client._fetch_one("RELIANCE")

    assert result["news_score"] == 0.4
    assert result["social_score"] == -0.2
    assert result["social_item_count"] == 2
    assert result["combined_score"] == 0.1
    assert result["context_only"] is True
