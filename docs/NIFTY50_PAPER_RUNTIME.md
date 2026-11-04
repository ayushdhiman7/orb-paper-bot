# Nifty 50 batch paper runtime

## Scope

The opt-in runner is `nifty50_runner.py`. It uses the official NSE Nifty 50 constituent list, resolves Angel One NSE cash-equity tokens, subscribes through the Angel One SmartAPI WebSocket V2 SNAP_QUOTE feed, collects completed 5-minute candles, requests one Gemini batch review for the complete eligible candidate set, applies deterministic risk validation and writes approved paper entries to `paper_trades`.

It does not submit broker orders. The legacy `bot.py` entry point remains unchanged; the new runner is a separate opt-in process.

## Required environment

- `ORB_RUNTIME_MODE=nifty50_batch` (explicit opt-in guard)
- Existing Angel One credentials: `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET` (the names are read by `angel_feed.py`)
- `GEMINI_API_KEY`
- `SUPABASE_URL` and `SUPABASE_KEY`
- Existing Telegram credentials if alerts are required
- Existing paper risk settings: `CAPITAL`, `RISK_PER_TRADE_PCT`, `DAILY_LOSS_CAP_PCT`, `MAX_TRADES_PER_DAY`, `SLIPPAGE_PCT`, `COST_PCT`
- Optional sentiment: `SENTIMENT_SERVICE_URL`, `SENTIMENT_API_TOKEN`, `SENTIMENT_LOOKBACK_MINUTES` (default 180). News sentiment is context only, cached for five minutes, and currently supports the five reviewed aliases RELIANCE, TCS, INFY, HDFCBANK and ICICIBANK. Social sentiment is not yet connected.

The runner refuses to use Yahoo prices. It skips a scan unless all 50 constituents have fresh WebSocket quote evidence. A failed universe refresh or WebSocket startup aborts startup.

## Database migration

Before running the new runner, apply `supabase/migrations/202611040001_nifty50_ai_trade_levels.sql`. This adds nullable columns for the AI-selected stop, target, confidence and rank. The runner persists those values with each AI-approved paper entry and restores them on restart.

The separate manual-exit migration from PR #20 must also be applied before manual-exit requests can work. Confirm the actual Supabase `paper_trades.id` type matches the `manual_exit_requests.trade_id` type before applying it.

## Start command

After reviewing the code and applying the required migrations/configuration, the process entry point is:

```bash
ORB_RUNTIME_MODE=nifty50_batch python nifty50_runner.py
```

Do not run this alongside the existing bot service. Both use the same single-instance lock and the second process should exit.

## Not yet validated

- Actual Angel One SNAP_QUOTE entitlement, 50-token subscription acceptance, reconnect and packet freshness must be tested with the user's account during market hours.
- The runner is not installed into the EC2 systemd unit by this code change. Do not change the production service until PR review, CI and account-level validation are complete.
- Social-media sentiment collection still requires a supported provider/API and credentials; no scraping or terms bypass is used.
- AI position-management actions are not yet wired into the runner; deterministic stop, target, daily loss cap, square-off and manual exit remain active.
- The Nifty 50 sentiment service is not connected to the candidate context yet; sentiment remains optional and does not affect this runner.
- Backtest and multi-session paper acceptance criteria require real historical/paper-session evidence and cannot be certified from unit tests alone.

## Safety

Paper-only. No broker order methods are used. Gemini output is never executed directly: it must pass the deterministic validator and final paper sizing checks. Any missing feed, invalid batch, quota/audit failure or persistence error prevents new entries.
