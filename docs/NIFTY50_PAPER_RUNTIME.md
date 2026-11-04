# Nifty 50 batch paper runtime

## Scope

The opt-in runner is nifty50_runner.py. It uses the official NSE Nifty 50 constituent list, resolves Angel One NSE cash-equity tokens, subscribes through the Angel One SmartAPI WebSocket V2 SNAP_QUOTE feed, maintains completed 1-minute and 5-minute candles, requests one Gemini batch review for the complete eligible candidate set, applies deterministic risk validation, and writes approved paper entries to the existing paper_trades ledger.

Open positions are reviewed as a batch by the AI position manager. Its proposed stop, target, and exit actions are validated against deterministic rules. Deterministic +1R / +1.5R / +2R protection remains active independently of AI. The dashboard exposes versioned runtime settings, manual paper exits, and an emergency stop. A durable once-per-session summary is persisted and delivered to Telegram and the dashboard webhook after all paper positions are closed.

The runner does not submit broker orders. The legacy bot.py entry point remains separate; this is an explicit opt-in process.

## Market data

- Angel One SmartAPI WebSocket V2 SNAP_QUOTE mode (3), NSE cash exchange type (1).
- The universe must contain exactly 50 unique current NSE constituents with unique Angel One cash tokens.
- Quotes must have fresh receive and exchange timestamps. Stale/disconnected quotes are rejected.
- There is no Yahoo fallback in this runtime.
- The SDK has bounded reconnect attempts; if its connection thread exits, the runner attempts a fresh login and resubscription after a 30-second backoff.
- A full market-session test with the actual account is still required to prove entitlement and packet coverage.

## Required environment

- ORB_RUNTIME_MODE=nifty50_batch (explicit opt-in guard)
- Angel One credentials: ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
- GEMINI_API_KEY (optional GEMINI_MODEL override)
- SUPABASE_URL and SUPABASE_KEY
- Telegram credentials if alerts are required: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- Existing paper sizing settings: CAPITAL, SLIPPAGE_PCT, COST_PCT
- Optional sentiment: SENTIMENT_SERVICE_URL and optional SENTIMENT_API_TOKEN

The dashboard-managed settings table controls risk per trade, daily loss cap, max open positions, max trades, scan interval, position review interval, stale quote tolerance, R-based protection thresholds, AI position confidence, forced square-off, sentiment enablement, AI position-management enablement, and emergency stop. Paper-only mode cannot be disabled.

## Sentiment

Google News RSS plus FinTwitBERT is optional context only. It is requested only for already-qualified candidates and cannot create, remove, reverse, or veto ORB signals. The current reviewed alias list supports RELIANCE, TCS, INFY, HDFCBANK, and ICICIBANK. News and social scores are represented separately; social remains unavailable until a permitted source is approved and configured.

The selected social source is Reddit, subject to explicit Reddit Data API approval and OAuth credentials. No X API integration or page scraping is included. See docs/NIFTY50_PAPER_RUNBOOK.md for the current access gate.

## Database migrations

Apply pending migrations in timestamp order using the approved Supabase process. This repository change does not execute them:

1. supabase/migrations/202611030001_manual_exit_requests.sql
2. supabase/migrations/202611040001_nifty50_ai_trade_levels.sql
3. supabase/migrations/202611040002_orb_bot_settings.sql
4. supabase/migrations/202611040003_initial_stop.sql
5. supabase/migrations/202611040004_bot_session_reports.sql

Verify schema and type compatibility before enabling the runner. The original stop is persisted separately from the active protective stop so R calculations remain stable after AI stop changes and process restarts.

## Install and start

Install the repository requirements, which include the pinned SmartAPI and pyotp dependencies:

    pip install -r requirements.txt

After applying migrations, configuring private environment variables, and completing the real-account SNAP_QUOTE acceptance test, start the opt-in runner:

    ORB_RUNTIME_MODE=nifty50_batch python nifty50_runner.py

Do not run this alongside the legacy bot service. Both use the same single-instance lock and the second process should exit.

## Validation state

Automated coverage includes universe validation, feed freshness, WebSocket subscription and reconnect supervision, batch candidate validation, paper sizing, stop protection for long and short positions, AI position batch parsing, dashboard setting validation, manual-exit safeguards, and paper-entry persistence.

The following remain operator acceptance steps and are not proven by mocked CI:
- A point-in-time Nifty 50 historical backtest of this AI batch runtime is not yet certified. The existing backtest.py is a short Yahoo-history legacy ORB smoke test; it is not Phase 9 sign-off. Avoid survivorship/look-ahead bias by using historical constituents and archived sentiment snapshots.
- Actual Angel One SNAP_QUOTE entitlement and fresh packet receipt using the account's API key, JWT and feed token.
- Full-session symbol coverage and disconnect/reconnect behavior during NSE market hours.
- Applying and verifying the pending Supabase migrations.
- Several separate paper sessions reviewing ledger reconciliation, costs, duplicate prevention, stop/target behavior and restart restoration.

## Safety and rollout

Paper-only. No broker order methods are used. Gemini output is never executed directly: it must pass deterministic validation and final paper sizing. Missing feed data, invalid or incomplete AI batches, quota/audit failures, or persistence errors prevent new entries.

The PR does not install or switch the EC2 systemd service and does not deploy to EC2. Do not merge to main until the operator-owned acceptance steps are complete; a push to main can trigger the dashboard deployment workflow.