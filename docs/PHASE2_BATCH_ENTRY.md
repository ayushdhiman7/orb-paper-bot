# Phase 2 batch-entry decision contract

## Scope of this slice

This change adds a pure, offline batch response parser and deterministic validation
contract. It does **not** call Gemini, collect market data, alter `bot.py`, write
Supabase rows, or open paper positions. Existing ORB entries and exits are unchanged.

## Batch response contract

- One request represents the entire eligible-candidate batch.
- The response must contain exactly one decision for every requested symbol.
- Allowed decisions are BUY, SELL, and SKIP.
- Confidence must be finite and within 0..1; reason must be 1..300 characters.
- Rank must be a unique positive integer.
- BUY/SELL require positive stop and target values. SKIP must have null stop/target.
- Missing, duplicate, unexpected, malformed, or extra top-level fields reject the batch.

## Deterministic validation

The caller supplies an immutable portfolio snapshot and candidate facts. The validator:

- Rejects AI directions that reverse the candidate's existing ORB breakout direction.
- Enforces configured confidence, open-position, daily-trade and daily-loss limits.
- Validates BUY stop < current price < target and SELL target < current price < stop.
- Sizes accepted entries against the configured per-trade cash-risk budget and available
  cash, processing candidates in AI rank order.
- Returns explicit rejection reasons; it never silently converts an invalid decision
  into an entry.

The result is a proposal only. The eventual integration must re-check live portfolio
state and recompute quantity using the existing bot fill, slippage, fee and persistence
functions immediately before a paper entry. A stale portfolio snapshot must never be
used as authorization to open a position.

## Still required before integration

1. Candidate collection for the full configured Nifty 50 universe.
2. Completed 5-minute candle/EMA20/VWAP/ATR14 and timestamped sentiment evidence.
3. One batch Gemini transport using the durable quota and AI audit layers.
4. Telegram output including AI confidence, rationale, evidence and deterministic risk verdict.
5. Dashboard configuration, emergency stop, persistence/restart semantics and end-to-end paper tests.
6. Controlled Angel One SNAP_QUOTE/WebSocket account validation.

Paper-only remains mandatory. No broker order endpoint or live-trading path is introduced.
