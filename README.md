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