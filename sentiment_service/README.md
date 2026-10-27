# FinTwitBERT Sentiment Service

Standalone Python API for scoring financial text. It does not fetch news or social media, generate trade signals, or place orders.

## Run locally

```bash
cd sentiment_service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

The first startup downloads the public Hugging Face model weights. A Hugging Face token is not normally required for this public model; never commit a token. The model is loaded once per service process, not on every request.\n\n## Google News RSS (no API key)\n\nThe `rss_news.py` adapter fetches public Google News RSS feeds for symbols with a reviewed alias list in `aggregation.py`. It normalizes titles, descriptions, publication timestamps, fetch timestamps, source IDs, links, and explicit symbol matches. It uses only Python's standard library. Keep polling modest and cache results; RSS availability, coverage, and freshness are not guaranteed.\n\nFrom the `sentiment_service` directory, a basic local check can be run with:\n\n```bash\npython -c \'from datetime import datetime, timezone; from rss_news import fetch_google_news; print(fetch_google_news(["RELIANCE.NS"], fetched_at=datetime.now(timezone.utc)))\'\n```\n\nThis performs a network request to Google News RSS. RSS collection is currently a standalone adapter; it is not connected to the ORB entry logic. The next step is to pass eligible items through `/score` and the time-safe aggregation layer in shadow mode.

- `GET /health`: model readiness and version.
- `POST /score`: batch sentiment scores. Example:

```json
{
  "items": [
    {"id": "news-123", "text": "Company reports stronger quarterly revenue"},
    {"id": "post-456", "text": "This stock is a disaster"}
  ]
}
```

Response includes the raw model label, a semantic label only when the label name is recognizable, full probabilities, confidence, SHA-256 text hash, model revision, and scoring timestamp. Unknown labels are preserved rather than guessed.

For deployment, set `APP_ENV=production` and a strong `SENTIMENT_API_TOKEN`; requests to `/score` must include `Authorization: Bearer <token>`. Never commit the token. Use HTTPS and restrict access to the service.

If model startup fails, the service remains available for health checks but `/score` returns HTTP 503. It never fabricates a neutral score. This service is experimental and for paper-trading research only.
