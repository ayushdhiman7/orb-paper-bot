"""Standalone FinTwitBERT inference API. This service never places trades."""
from __future__ import annotations

import hashlib
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import torch
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentiment_service")

MODEL_ID = os.getenv("SENTIMENT_MODEL_ID", "StephanAkkerman/FinTwitBERT-sentiment")
MODEL_REVISION = os.getenv("SENTIMENT_MODEL_REVISION", "main")
APP_VERSION = os.getenv("SENTIMENT_APP_VERSION", "0.1.0")
MAX_BATCH_SIZE = int(os.getenv("SENTIMENT_MAX_BATCH_SIZE", "16"))
MAX_TEXT_LENGTH = int(os.getenv("SENTIMENT_MAX_TEXT_LENGTH", "4000"))
MAX_TOKEN_LENGTH = int(os.getenv("SENTIMENT_MAX_TOKEN_LENGTH", "256"))
API_TOKEN = os.getenv("SENTIMENT_API_TOKEN", "")
APP_ENV = os.getenv("APP_ENV", "development")


class TextInput(BaseModel):
    id: str | None = Field(default=None, max_length=128)
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value.strip()


class ScoreRequest(BaseModel):
    items: list[TextInput] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class SentimentResult(BaseModel):
    id: str | None
    text_hash: str
    label: str
    raw_label: str
    confidence: float
    probabilities: dict[str, float]


class ScoreResponse(BaseModel):
    model_id: str
    model_revision: str
    app_version: str
    scored_at: datetime
    results: list[SentimentResult]


class NewsSentimentRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    lookback_minutes: int = Field(default=180, ge=1, le=1440)
    max_items_per_query: int = Field(default=20, ge=1, le=50)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ModelRuntime:
    """Lazy-loadable model runtime, separated for testability."""

    def __init__(self) -> None:
        self.tokenizer: Any = None
        self.model: Any = None
        self.id2label: dict[int, str] = {}
        self.device = "cpu"
        self.error: str | None = None

    def load(self) -> None:
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION
            )
            self.model.eval()
            self.id2label = {
                int(index): str(label)
                for index, label in self.model.config.id2label.items()
            }
            if not self.id2label:
                raise RuntimeError("Model config does not provide id2label")
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            self.error = None
            logger.info(
                "Model loaded model_id=%s revision=%s labels=%s device=%s",
                MODEL_ID, MODEL_REVISION, self.id2label, self.device,
            )
        except Exception as exc:
            self.tokenizer = None
            self.model = None
            self.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Unable to load sentiment model")

    @property
    def ready(self) -> bool:
        return self.tokenizer is not None and self.model is not None

    @staticmethod
    def _semantic_label(raw_label: str) -> str:
        """Map recognizable label names without relying on numeric label order."""
        label = raw_label.lower().replace("_", "").replace("-", "").strip()
        if any(term in label for term in ("positive", "bullish", "pos")):
            return "positive"
        if any(term in label for term in ("negative", "bearish", "neg")):
            return "negative"
        if any(term in label for term in ("neutral", "neu")):
            return "neutral"
        # Preserve unknown model labels; do not invent a semantic interpretation.
        return raw_label

    def score(self, items: list[TextInput]) -> list[SentimentResult]:
        if not self.ready:
            raise RuntimeError("Sentiment model is not available")
        texts = [item.text for item in items]
        encoded = self.tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=MAX_TOKEN_LENGTH,
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with torch.inference_mode():
            logits = self.model(**encoded).logits
            batch_probabilities = torch.softmax(logits, dim=-1).cpu().tolist()

        output: list[SentimentResult] = []
        for item, row in zip(items, batch_probabilities, strict=True):
            probabilities = {
                self.id2label[index]: float(probability)
                for index, probability in enumerate(row)
                if index in self.id2label
            }
            if len(probabilities) != len(row):
                raise RuntimeError("Model output labels do not match output dimensions")
            top_index = max(range(len(row)), key=row.__getitem__)
            raw_label = self.id2label[top_index]
            output.append(SentimentResult(
                id=item.id,
                text_hash=hashlib.sha256(item.text.encode("utf-8")).hexdigest(),
                label=self._semantic_label(raw_label),
                raw_label=raw_label,
                confidence=float(row[top_index]),
                probabilities=probabilities,
            ))
        return output


runtime = ModelRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime.load()
    yield


app = FastAPI(
    title="FinTwitBERT Sentiment Service",
    version=APP_VERSION,
    description="Financial text sentiment inference only; not a trading or prediction service.",
    lifespan=lifespan,
)


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN:
        if APP_ENV.lower() in {"production", "prod"}:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SENTIMENT_API_TOKEN must be configured in production",
            )
        return
    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ready" if runtime.ready else "unavailable",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "app_version": APP_VERSION,
        "error": runtime.error,
        "paper_trading_only": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/score", response_model=ScoreResponse, dependencies=[Depends(require_api_token)])
def score(request: ScoreRequest) -> ScoreResponse:
    if not runtime.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sentiment model is unavailable; no sentiment result was produced",
        )
    try:
        results = runtime.score(request.items)
    except Exception as exc:
        logger.exception("Sentiment scoring failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sentiment scoring failed; no sentiment result was produced",
        ) from exc
    return ScoreResponse(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        app_version=APP_VERSION,
        scored_at=datetime.now(timezone.utc),
        results=results,
    )


@app.post("/research/news-sentiment", dependencies=[Depends(require_api_token)])
def research_news_sentiment(request: NewsSentimentRequest) -> dict[str, Any]:
    """Fetch and score Google News RSS for shadow research only; never places trades."""
    from aggregation import DEFAULT_SYMBOL_ALIASES
    from news_pipeline import result_to_dict, run_news_sentiment

    if request.symbol not in DEFAULT_SYMBOL_ALIASES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No reviewed company aliases configured for {request.symbol}",
        )
    if not runtime.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sentiment model is unavailable; no sentiment result was produced",
        )
    try:
        aggregated, articles = run_news_sentiment(
            symbol=request.symbol,
            runtime=runtime,
            lookback_minutes=request.lookback_minutes,
            max_items_per_query=request.max_items_per_query,
        )
    except RuntimeError as exc:
        logger.exception("News sentiment collection failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="News collection or sentiment scoring failed; no trading decision was made",
        ) from exc
    except Exception as exc:
        logger.exception("News sentiment research endpoint failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="News sentiment research failed; no trading decision was made",
        ) from exc
    return {
        "mode": "shadow_research_only",
        "paper_trading_only": True,
        "trade_decision_changed": False,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "aggregation": result_to_dict(aggregated),
        "articles": articles,
    }
