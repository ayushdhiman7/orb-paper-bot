# Nifty 50 Paper Runner — Phase 3 Runbook

## Safety boundary

- This runner is paper-only. It does not import or call SmartAPI order-placement methods.
- Angel One SmartAPI WebSocket V2 in SNAP_QUOTE mode is the only price source for this runtime.
- A missing, disconnected, or stale quote blocks entries and prevents price-dependent exits; there is no Yahoo fallback.
- The existing ORB signal, deterministic portfolio limits, adverse paper fills, fees, and slippage remain authoritative. AI ranks/reviews candidates but cannot bypass deterministic validation.
- Do not enable this runtime on a live account or treat paper results as proof of live execution quality.

## Required configuration

Provide these values through the existing private environment file / systemd environment. Never commit them or paste them into chat.

| Purpose | Environment variables |
|---|---|
| Angel One login | ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET |
| Supabase paper ledger | SUPABASE_URL, SUPABASE_KEY |
| Gemini batch review | GEMINI_API_KEY (optional model override: GEMINI_MODEL) |
| Telegram notifications | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID |
| Optional research-only sentiment | SENTIMENT_SERVICE_URL, optional SENTIMENT_API_TOKEN |
| Feed tuning | ANGEL_MAX_STALE_SECONDS (default 45), ANGEL_WS_CONNECT_TIMEOUT (default 20) |

The accepted Angel credential aliases are defined in angel_feed.py. The WebSocket runtime uses SmartAPI V2 SNAP_QUOTE (mode 3) for NSE cash (exchange type 1). Python dependencies for the SmartAPI client are included through requirements-angelone-test.txt, referenced by requirements.txt.

## Database migrations — manual operator step

Apply pending SQL migrations in timestamp order using the project's approved Supabase process. This repository change does not execute migrations:

1. supabase/migrations/202611030001_manual_exit_requests.sql
2. supabase/migrations/202611040001_nifty50_ai_trade_levels.sql
3. supabase/migrations/202611040002_orb_bot_settings.sql
4. supabase/migrations/202611040003_initial_stop.sql
5. supabase/migrations/202611040004_bot_session_reports.sql

The initial-stop migration is idempotent. It backfills legacy rows from their current stop as the safest available baseline; new Nifty 50 entries persist the true original stop. Verify that paper_trades.initial_stop, paper_trades.stop, paper_trades.target, paper_trades.ai_confidence, paper_trades.ai_rank, manual_exit_requests, and orb_bot_settings exist before starting the runner.

## Real-account feed acceptance test

This must be completed with the actual Angel One account before enabling the Nifty 50 runner. It validates login, permission to subscribe in SNAP_QUOTE mode, and receipt of fresh quote packets. It does not place orders.

Run from the repository virtual environment during NSE market hours:

    python - <<'PY'
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from nifty50_bot_runtime import start_feed

    universe, feed = start_feed()
    try:
        deadline = time.monotonic() + 90
        fresh = {}
        while time.monotonic() < deadline:
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            for row in universe:
                quote = feed.quote(row["symbol"], now)
                if quote is not None:
                    fresh[row["symbol"]] = quote
            time.sleep(1)
        print(f"Universe: {len(universe)}")
        print(f"Fresh SNAP_QUOTE symbols observed: {len(fresh)}")
        for symbol, quote in sorted(fresh.items()):
            print(symbol, quote["price"], quote["event_time"].isoformat())
        if not fresh:
            raise SystemExit("FAIL: no fresh SNAP_QUOTE packets received")
    finally:
        feed.stop()
    PY

Record the account's successful login, subscription callback, fresh quote count, and any permission/rate-limit errors. A successful WebSocket handshake alone is not sufficient; at least one fresh exchange-timestamped quote must be received. Check symbol-level coverage over a normal market interval before relying on the full universe. Do not work around denied SNAP_QUOTE access by switching to delayed data.

The SDK uses its bounded reconnect attempts. If its connection thread exits, the runner supervises it and attempts a fresh login/subscription after a 30-second backoff. During disconnect/reconnect, stale quotes remain invalid and entries remain blocked. Validate this with the account and network conditions before production-like paper sessions.


## Sentiment source scope

The currently wired runtime sentiment client is optional, cached Google News RSS context for the five reviewed aliases in sentiment_client.py. It is passed only for already-qualified ORB candidates and cannot create, remove, reverse, or veto an ORB signal. The service reports news and social fields separately; social remains unavailable until an approved source is configured.

The planned free social source is Reddit, not X. Do not scrape Reddit pages or call the Data API until the app has explicit access approval and OAuth credentials. Reddit's current Data API guidance requires OAuth and says developers must request access; it also requires honoring deletion requests and API rate limits. See the [Reddit Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki), [Developer Platform & Accessing Reddit Data](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data), and [Data API Terms](https://redditinc.com/policies/data-api-terms). No X API integration is planned because the selected source constraint was free-only.

## Start the opt-in paper runner

Only after migrations and the real-account acceptance test pass:

    ORB_RUNTIME_MODE=nifty50_batch python nifty50_runner.py

The runner checks the exact 50-member NSE constituent list against Angel One's current NSE cash scrip master and refuses partial/ambiguous mappings. It acquires the existing single-instance lock, verifies Supabase state, restores open paper positions and AI levels, then starts the feed. Do not run this alongside the legacy bot process.

Runtime settings are stored in orb_bot_settings and refreshed by the runner every 15 seconds. The dashboard's Settings page controls scan cadence, risk caps, position limits, R-based protection, AI review confidence, sentiment context, square-off, stale-quote tolerance, and the emergency stop. Paper-only execution is not configurable.

## Acceptance checklist before calling Phase 3 operational

- [ ] CI is green on the exact PR head commit.
- [ ] Pending Supabase migrations have been applied and schema verified by the operator.
- [ ] Actual account SNAP_QUOTE login, subscription, and fresh quote receipt are confirmed.
- [ ] A full market session confirms current 50-symbol universe/token mapping and quote freshness behavior.
- [ ] Disconnect/reconnect test confirms stale data is rejected and no fallback feed is used.
- [ ] Paper entry writes the trade row before in-memory portfolio state changes.
- [ ] Restart restores open position, original stop, current stop, target, AI confidence, and rank.
- [ ] +1R, +1.5R, and +2R protection behavior is checked for long and short paper positions, including fees and restart.
- [ ] AI position review handles the complete open portfolio; malformed, partial, unavailable, or unsafe decisions are rejected.
- [ ] Failed database writes halt new entries and do not mutate in-memory protection levels.
- [ ] Dashboard settings save with version checks; invalid cross-field R thresholds are rejected.
- [ ] Manual exit only closes a paper position at a fresh Angel One quote.
- [ ] Telegram notifications cover entry, exit, risk rejection, position review, reconnect, emergency stop, and persistence halt.
- [ ] At least several separate paper sessions are reviewed for ledger consistency, fees, slippage, and no duplicate positions.

## Operator-owned steps / explicit exclusions

The actual-account SNAP_QUOTE test, Supabase migration execution, and EC2 service/deployment changes require the operator's account and approval. Do not run the dashboard deployment workflow or merge this PR to main as part of this runbook; a push to main can deploy the dashboard to EC2. The EC2 deployment remains user-managed and untouched.
