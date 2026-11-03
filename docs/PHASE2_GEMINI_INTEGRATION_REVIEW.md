# Nifty 50 Gemini integration groundwork

This branch combines the deterministic Nifty 50 universe resolver and candidate collector
with the existing batch-entry parser and deterministic paper-risk contract.

## Included
- Single-request Gemini batch transport through the existing durable quota and append-only audit gates; exact candidate coverage is required and failures return no usable decision.
- Final paper execution sizing helper that rechecks a fresh portfolio snapshot and recomputes quantity after adverse slippage and entry fees; it produces a plan only and does not persist or submit orders.
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
3. Candidate collection now requires timestamped quote evidence (`event_time` and `received_at`) and rejects disconnected/stale evidence through the WebSocket adapter. Actual-account feed behaviour still needs validation.
4. The AI batch validator still provides preliminary sizing only. The new final execution helper recomputes quantity using adverse slippage and entry fees, and rechecks portfolio limits. It must be wired to a fresh state snapshot in the bot loop before persistence.
5. Actual Angel One SNAP_QUOTE access, 50-token subscription behaviour, heartbeat and reconnect handling still require testing with the user's account.

## Integration gates
- Gemini batch transport is implemented and covered by tests. Invalid, unavailable, quota-blocked or unauditable output returns no usable batch.
- Re-read portfolio state immediately before each paper entry, recompute slippage/fees/sizing, and enforce limits again. The sizing helper exists but is not yet wired into bot.py.
- Do not fall through to the legacy per-symbol entry path if the batch AI stage fails.
- Include confidence, rationale, evidence and deterministic risk verdict in Telegram.
- Keep all broker order endpoints out of the implementation.
- No Supabase migration, EC2 deployment, service restart or production configuration
  change is part of this branch.

This is groundwork only. It does not call Gemini, activate the WebSocket feed in bot.py,
or create paper positions.
