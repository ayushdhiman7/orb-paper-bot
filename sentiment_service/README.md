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

The first startup downloads the Hugging Face model weights. The model is loaded once per service process, not on every request.

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
