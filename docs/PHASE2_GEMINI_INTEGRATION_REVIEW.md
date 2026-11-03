# Nifty 50 Gemini integration groundwork

This branch combines the deterministic Nifty 50 universe resolver and candidate collector
with the existing batch-entry parser and deterministic paper-risk contract.

## Included
- Nifty 50 universe/token resolver and WebSocket adapter from the parent branch.
- Deterministic 50-stock ORB candidate collector.
- Exact-coverage BUY/SELL/SKIP batch response parser.
- Deterministic portfolio/risk validator and its tests.
- CI inclusion for the batch-entry contract tests.

## Review findings to resolve before runtime wiring
1. The WebSocket feed's `last()` checks local receive age but does not require
   `connected=True` or validate the exchange-event timestamp age. A recently received
   stale/replayed packet could still be treated as current.
2. The WebSocket subscription currently sends all 50 tokens in one request. Account/API
   subscription limits and heartbeat/reconnect behaviour have not been verified.
3. The candidate collector delegates quote freshness to the feed adapter and accepts a
   float-only quote interface. Runtime integration must require a healthy feed and
   timestamped, fresh quote evidence for every candidate.
4. The batch sizing contract does not include slippage, brokerage, taxes or other costs.
   Runtime must recompute quantity and affordability using the existing paper fill/cost
   implementation immediately before persistence.
5. The batch validator's positive-number helper currently coerces booleans to 1.0.
   Harden numeric input validation before using AI output at runtime.

## Integration gates
- Add a single Gemini request for the entire candidate batch, using the durable quota and
  append-only audit layer. Invalid, unavailable, quota-blocked or unauditable output must
  result in zero entries for that batch.
- Re-read portfolio state immediately before each paper entry and enforce limits again.
- Do not fall through to the legacy per-symbol entry path if the batch AI stage fails.
- Include confidence, rationale, evidence and deterministic risk verdict in Telegram.
- Keep all broker order endpoints out of the implementation.
- No Supabase migration, EC2 deployment, service restart or production configuration
  change is part of this branch.

This is groundwork only. It does not call Gemini, activate the WebSocket feed in bot.py,
or create paper positions.
