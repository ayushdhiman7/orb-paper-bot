`notify.py` sends a Telegram message for every entry, exit and halt (loss cap, missing price, database write failure). `watchdog.py` runs every 5 minutes from its own systemd timer, so it still works when the bot is dead, and alerts once if the bot is not running or an open trade's price has not updated for 10 minutes (and once more when it recovers). Without the two Telegram values in `.env` everything is a silent no-op.

Setup: in Telegram talk to @BotFather, send `/newbot`, copy the token. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `"chat":{"id":...}`. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (never in chat), then run `bash deploy/install.sh` once to install the watchdog timer.

## Phase 0 safety: single bot instance and rollback

The bot acquires a non-blocking Linux `flock` on `/tmp/orb-paper-bot.lock` before startup checks or trading logic. The systemd service and direct `python bot.py` runs use the same lock path. A second process exits without entering the trading loop. The kernel releases the lock automatically when the owning process exits or crashes; the lock file itself may remain and is harmless.

After changing only the bot systemd unit, install that unit without running the full installer (which also installs dependencies and enables all timers):

```bash
cd ~/orb-paper-bot
sed -e "s|__DIR__|$PWD|g" -e "s|__USER__|$(id -un)|g" deploy/orb-bot.service | sudo tee /etc/systemd/system/orb-bot.service >/dev/null
sudo systemctl daemon-reload
systemctl cat orb-bot.service
```

Do not manually delete the lock file to clear a lock. First verify no bot process is running; an unlocked file does not prevent a future start.

For rollback steps and the limits of the automatic updater, see [deploy/ROLLBACK.md](deploy/ROLLBACK.md).

## Nifty 50 batch paper runtime (opt-in)

The default `ORB_RUNTIME_MODE=legacy` preserves the existing strategy. To select the new Nifty 50 batch coordinator, set `ORB_RUNTIME_MODE=nifty50_batch` only after all rollout gates below are complete.

The Nifty 50 mode fetches the current NSE constituent CSV and Angel One scrip master, requires exactly 50 unique NSE cash-equity token mappings, and starts the Angel One WebSocket V2 SNAP_QUOTE feed. It does not use Yahoo as a fallback. A feed disconnect halts new entries. Every scan sends the full eligible candidate batch to Gemini once, then deterministic portfolio/risk checks and cost-aware sizing run before a simulated paper entry is persisted.

Runtime controls:
- `NIFTY50_SCAN_SECONDS=180` (3-minute candidate scan)
- `NIFTY50_MAX_POSITIONS=3`
- `NIFTY50_MIN_CONFIDENCE=0.65`

Before enabling this mode:
1. Apply `supabase/migrations/202611040001_ai_position_risk_metadata.sql` to the project database.
2. Confirm the Angel One account is entitled to SNAP_QUOTE mode 3 and can subscribe to all 50 NSE cash tokens. Confirm fresh packets and reconnect behaviour during market hours.
3. Confirm `GEMINI_API_KEY`, durable quota/audit paths, Supabase and Telegram configuration are valid.
4. Start in paper-only mode and verify the feed, scan cadence, Telegram decision details, paper rows and restored stop/target values.
5. Keep the legacy mode configured for rollback. Do not run the new mode until the migration and account validation are complete.

This runtime never calls broker order endpoints. It does not enable live trading. Dashboard settings UI, AI position-management actions, manual-exit migration/token rollout and multi-session paper acceptance remain separate rollout tasks.
