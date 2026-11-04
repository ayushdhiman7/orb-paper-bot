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
