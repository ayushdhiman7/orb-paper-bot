# Phase 2 — AI authority and position management

## Agreed operating model

- Universe: Nifty 50 eligible stocks.
- Entry scan: batch all eligible candidates into one AI review every 180 seconds; AI may return BUY, SELL, or SKIP for each candidate.
- Open-position review: every 300 seconds, plus event-triggered reviews when a material market, feed, or sentiment event is detected.
- Position actions: HOLD, MOVE_SL, LOCK_PROFIT, UPDATE_TARGET, EXIT.
- AI may propose entries and management changes; deterministic risk validation is the final authority before any paper action.
- Gemini request budget: 100 requests per IST day and 5 requests per rolling minute.
- Sentiment evidence: exchange, news, and social sources; refresh on a 5-minute cadence. Sentiment remains evidence supplied to the decision process, not a replacement for risk controls.
- Risk defaults retained from current bot unless separately configured: 1% capital risk per trade, maximum 2 simultaneous positions, 3 entries per day, 3% daily loss cap, and 15:15 IST square-off.
- Emergency stop is a hard safety control and must close all paper positions; it must not be delegated to AI.
- Paper-only. No live broker order path may be introduced.

## Deterministic position-action validation

- HOLD and EXIT are valid only with a valid action and sufficient confidence.
- MOVE_SL can only tighten the existing stop; it cannot widen risk or cross the current mark.
- LOCK_PROFIT can only set a protective stop beyond entry in the profitable direction and before the current mark.
- UPDATE_TARGET can only extend the target further in the profitable direction and beyond the current mark.
- Missing, malformed, duplicate, unknown-symbol, low-confidence, or out-of-range AI output is rejected. It never becomes an implicit BUY.
- Existing hard stop, target, daily loss cap, max positions, max entries, emergency stop and 15:15 square-off remain deterministic overrides.

## Implemented in this first Phase 2 slice

- Typed management-action contract and strict JSON parser.
- Deterministic validators for BUY/SELL stop and target proposals.
- Batch entry-response parser requiring exactly one decision per requested candidate.
- Configurable defaults and environment validation for scan cadence, review cadence, max positions, risk, quota, confidence, trade cap, daily loss cap and square-off.
- Unit tests for the safety rules and quota limits.

## Not yet wired into the running bot

This first slice intentionally does not change bot.py, create/alter Supabase tables, call Gemini, activate the WebSocket feed, add dashboard write controls, or send broker orders. The next Phase 2 slices must integrate the quota with every actual Gemini HTTP attempt, persist AI decisions and position state, feed technical and sentiment evidence to batch analysis, expose settings and emergency-stop controls in the dashboard, and validate Telegram reporting. This separation prevents an unfinished AI proposal engine from changing the existing paper strategy.

## Validation gates before Phase 2 can be considered complete

- Backtest: at least 100 out-of-sample trades across 60 sessions; profit factor >= 1.20; expectancy >= 0.15R; max drawdown <= 6R.
- Paper validation: at least 30 sessions and 60 trades; zero unauthorized entries and zero risk-rule violations.
- AI output: invalid-response rate < 0.5%; P95 decision latency <= 15 seconds.
- Feed availability target: >= 99.5%.
- All tests, dashboard build, failure/timeout tests, persistence/restart tests and paper-only safety checks pass.
