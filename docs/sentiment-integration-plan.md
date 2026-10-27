# Sentiment integration plan — ORB paper bot

## Status / scope

Repository audited: ayushdhiman7/orb-paper-bot
Current branch: main
Baseline commit reviewed: 58e74e1d84e00c7db8cbc4dc3c9526bfc0411fc7
Do not alter the existing ORB entry/exit rules as part of the first sentiment experiment.

The repo currently contains bot.py, backtest.py, Supabase-backed paper trade and backtest logging, a static dashboard in docs/, GitHub Actions workflows, and requirements.txt. The public main branch does not currently contain the unpushed strategy-lab/Gemini files mentioned in the chat. Recover those local changes before merging this plan into an implementation.

## Design

Add a separate Python HTTP service, proposed directory sentiment_service/:
- FastAPI endpoints GET /health and POST /score.
- Load StephanAkkerman/FinTwitBERT-sentiment with Hugging Face Transformers once at process startup.
- Batch inference, max input length limit, input validation, timeout and health reporting.
- Return model label and probabilities as they are actually emitted by the model config; never assume numeric label order. Test labels from model.config.id2label at startup.
- Version the model/revision and app in every response/log.
- If model unavailable, return an explicit unavailable/error state. Never fabricate neutral sentiment.
- Deploy as a separate Python service (e.g. Render web service); the existing trading worker and GitHub Actions runner call it over internal HTTPS. Avoid downloading/loading the ~440 MB model on each scheduled GitHub Actions run.

## Data source adapters

Create provider-neutral interfaces:
- NewsArticle: provider, article_id/url, symbol candidates, headline, summary if licensed, published_at, fetched_at, source.
- SocialPost: provider, post_id/url, symbol candidates, text, posted_at, fetched_at, author/post metadata only if terms permit.
- Start with one licensed/accessible Indian market news source and one social provider/API with clear terms. Do not scrape sites or bypass rate limits/terms.
- Resolve NSE symbols and aliases explicitly (e.g. RELIANCE.NS -> Reliance Industries); require a symbol/entity match before attributing sentiment.
- Deduplicate near-identical syndicated headlines/reposts; drop retweets/reposts or down-weight them so viral repetition cannot dominate.
- Exclude timestamps after the decision time. Keep all timestamps timezone-aware and normalize to Asia/Kolkata.
- If source coverage is empty/stale, mark coverage unavailable rather than treating it as neutral.
- The model card is optimized for informal financial social text; validate news separately before pooling sources.

## Sentiment aggregation

For a proposed entry on symbol S at time T:
- Only use items published at or before T and within a configurable lookback window.
- Per item store model label, full probability vector, max probability, text hash, source/type, source URL/id, published/fetched timestamps, model revision and scoring timestamp.
- Aggregate recent, distinct items per symbol with capped item weights. First experiment should report news and social scores independently, then a combined score.
- Expose counts, weighted sentiment score, bullish/bearish/neutral shares, average/max confidence, data age and coverage warnings.
- Avoid treating model confidence as probability of a future stock return.

## Rollout / experiment

Phase 0: observation-only shadow mode; existing strategy still enters exactly as before. Record sentiment at signal time and the subsequent unmodified trade outcome.
Phase 1: run paired backtests for identical symbol/date universe:
  A. existing baseline unchanged
  B. news-only sentiment filter
  C. social-only sentiment filter
  D. combined sentiment filter
  E. optional combined filter + Gemini second-stage veto, only after A-D show enough coverage to justify it.
- Choose thresholds on training dates only. Report results on held-out chronological dates untouched during tuning.
- Include all-in Indian transaction costs applicable to the chosen instrument/broker, taxes/charges, spread and slippage. Avoid changing cost assumptions between variants.
- Report coverage, trade count, net P&L, expectancy, profit factor, win rate, drawdown, and per-symbol/source results. Keep missing sentiment as a separate bucket; do not silently drop those signals.
- If paired backtest lacks timestamped historical news/social data, don't backfill today's sentiment onto old trades or claim a valid sentiment backtest. Use shadow paper-trading prospectively to collect correctly timestamped samples.
- Only promote a filter to paper-trade gating after repeatable positive out-of-sample results. Still paper-only, no broker APIs or live orders.

## Integration points

bot.py:
- At signal time, call existing local sentiment client only if SENTIMENT_ENABLED=true.
- First mode is shadow: log result but do not alter entry outcome.
- Optional filter mode must be a separate explicit config, default off; reject a trade only under an explicit validated policy and only if score is fresh, entity-matched and sufficiently covered.
- On service timeout/error/stale data/ambiguous entity: bypass sentiment filter safely and record the fallback; do not present fallback as AI approval.
- Keep order simulation and existing risk limits unchanged.

backtest.py:
- Keep the baseline function/results reproducible and unchanged.
- Add optional signal annotations/filter config, but never request live current news/social data during historical simulation.
- Accept a historical timestamped sentiment dataset, aligned with the time each signal could have been known.
- Store per-variant metrics and experiment metadata to the existing backtest_runs table only after schema compatibility is checked.

Supabase:
- Prefer new sentiment_observations and sentiment_experiments tables rather than widening paper_trades with lots of raw text.
- Store URLs, IDs, hashes, timestamps, labels/probabilities, service/model version, symbol, data source and error/coverage status.
- Set retention policy and minimize raw social content; follow provider terms and RLS.
- Add policy migrations idempotently; inspect existing policies before create because duplicate policy creation can fail.

Dashboard:
- Add a Sentiment / Lab section only after service and schema are validated.
- Display coverage/data freshness, bullish/bearish/neutral breakdown, sentiment at signal time, baseline vs variant net performance, and errors.
- Label it experimental; do not display model output as financial advice or an assured prediction.

## Security and deployment

- A previously pasted Gemini key should be treated as compromised: revoke it and create a new key in AI Studio. Store only as a GitHub Actions secret / service environment variable; never commit it.
- Add only non-secret config to .env.example; ensure .env, model cache, logs containing personal data and keys are gitignored.
- Keep the model service API authenticated between bot and service (shared secret/token in deployment secret, HTTPS); rate-limit input and cap batch size.
- Keep all trading PAPER ONLY. Do not add broker execution endpoints or change paper mode.
- Pin dependencies after a clean Python 3.12 install; add unit tests that mock the model and news/social adapters so CI tests do not download the weights or require third-party credentials.

## Acceptance criteria

1. Baseline backtest outputs match the saved baseline when sentiment is disabled.
2. Unit tests cover model label mapping, no data, stale data, ticker matching, duplicate headlines, timeout, bad response, provider rate limit and unknown sentiment.
3. No future data leakage: every item is published at or before the signal timestamp.
4. Shadow mode never changes whether the existing strategy enters or exits.
5. Test variants share the same dates, symbols, position-sizing/risk rules and cost model.
6. Dashboard and Supabase log score version, source timestamps, data coverage, decision mode and error/fallback.
7. No live trading execution exists; paper-only default remains enforced.
8. GitHub Actions installs and tests without downloading the model; service deployment performs model startup and health checks separately.

## Immediate next steps

1. Recover or inspect Claude's unpushed local strategy-lab/Gemini changes; do not overwrite them.
2. Add a plan-only PR or branch before code changes.
3. Implement schemas, scoring service interface and mock tests first.
4. Decide the Indian market news and social data providers before implementing fetchers.
5. Run shadow paper collection before deciding any sentiment thresholds.
