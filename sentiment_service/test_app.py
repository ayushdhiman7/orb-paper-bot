import os

from fastapi.testclient import TestClient

# Ensure test imports are not treated as production deployments.
os.environ["APP_ENV"] = "test"
os.environ.pop("SENTIMENT_API_TOKEN", None)

import app as sentiment_app


def test_health_reports_unavailable_without_model():
    sentiment_app.runtime.tokenizer = None
    sentiment_app.runtime.model = None
    sentiment_app.runtime.error = "test model unavailable"
    with TestClient(sentiment_app.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["paper_trading_only"] is True


def test_score_returns_503_when_model_unavailable():
    sentiment_app.runtime.tokenizer = None
    sentiment_app.runtime.model = None
    with TestClient(sentiment_app.app) as client:
        # Avoid loading real weights during tests.
        sentiment_app.runtime.load = lambda: None
        response = client.post("/score", json={"items": [{"text": "Strong results"}]})
    assert response.status_code == 503
    assert "no sentiment result" in response.json()["detail"]


def test_blank_text_is_rejected():
    with TestClient(sentiment_app.app) as client:
        sentiment_app.runtime.load = lambda: None
        response = client.post("/score", json={"items": [{"text": "   "}]})
    assert response.status_code == 422


def test_semantic_label_mapping_does_not_assume_numeric_order():
    assert sentiment_app.ModelRuntime._semantic_label("LABEL_2") == "LABEL_2"
    assert sentiment_app.ModelRuntime._semantic_label("positive") == "positive"
    assert sentiment_app.ModelRuntime._semantic_label("NEGATIVE") == "negative"
    assert sentiment_app.ModelRuntime._semantic_label("neutral") == "neutral"
