# ORB Paper Trading Bot (NSE, intraday)

Opening-range-breakout bot that trades **fake money only**. No broker connection.

## What it does
- Pulls free 1-minute NSE data from Yahoo Finance (`yfinance`, delayed ~15 min).
- Marks the 9:15-9:30 IST high/low per stock, enters on a breakout, exits on stop-loss, target, or the 3:15 PM square-off.
- Risk rules: 1% risk per trade, 3% daily loss cap, max 3 trades/day, 0.10% round-trip cost + 0.05% slippage per side (adjustable via COST_PCT, SLIPPAGE_PCT; unverified estimates).
- Requires Supabase to persist paper trades and verify there are no unresolved open trades before startup. The bot fails closed when trade persistence fails; it does not treat CSV fallback as safe position state.

## Run locally
Install dependencies and configure Supabase first. Run `schema.sql` in the Supabase SQL editor, then set `SUPABASE_URL` and `SUPABASE_KEY` in your environment. Never commit credentials.

```bash
pip install -r requirements.txt
python bot.py
```
Run it on a weekday during market hours (9:15-15:30 IST). It sleeps otherwise. Startup refuses to proceed if Supabase is unavailable, if the open-trade check fails, or if unresolved open paper trades remain from an earlier process. The current version does not automatically restore in-memory positions; reconcile those records before restarting. Entry/close persistence failures halt new entries and retain unresolved positions rather than silently falling back to CSV.

## Supabase (required for safe paper-bot operation)
1. Create a project at supabase.com.
2. SQL Editor: run `schema.sql`.
3. Settings -> API: configure the project URL and a server-side key in `SUPABASE_URL` and `SUPABASE_KEY`. Never commit the key or expose a service-role key in browser code. The bot requires Supabase to verify startup state and durably log entries and closes.

## Deploy (free, GitHub Actions)
`.github/workflows/paper-trade.yml` starts the bot every weekday at about 9:35 AM IST and stops it after the 3:15 PM square-off.
1. Repo -> Settings -> Secrets and variables -> Actions -> New repository secret.
2. Add `SUPABASE_URL` and `SUPABASE_KEY` (service_role key).
3. Actions tab -> paper-trade-session -> Run workflow to test it by hand.
Notes: scheduled runs can start a few minutes late, GitHub pauses schedules after 60 days without repo activity, and it only runs on market days (holidays just end with 0 trades).

## Other hosting
The bot can also run as a long-running worker.
- **Free option:** a GitHub Actions cron is awkward for a long loop; the simplest free route is running it on your own PC/laptop during market hours, or Oracle Cloud's always-free VM.
- **Paid but easy:** Render background worker (`render.yaml` included, starter plan), Railway, or Fly.io.

## Dashboard (installable PWA)

The dashboard in `docs/` is a static page that reads `paper_trades` and `backtest_runs` directly through the Supabase REST API using the publishable/anon key. It does not use a login screen or the `dashboard-data` Edge Function. Read access is controlled by the Supabase grants and row-level security policies. Do not put a service-role key in browser code.
## Backtest
`backtest.py` replays the same rules on ~60 days of free 5-minute data with costs and slippage, tries 15 stop/target settings, and checks the best one on days it never saw. Run it from the Actions tab: backtest -> Run workflow, then open the run and read the summary. It is a smoke test, not proof of an edge.

## Before any real money
Paper trade 4-8 weeks and check the Supabase table. Past paper results do not guarantee live results. Going live would need a broker API (Angel One SmartAPI / Upstox) and checking SEBI's current algo-trading rules. Not financial advice.

## Automatic weekday runs (EC2)

The bot starts itself Mon-Fri at 09:05 IST through a systemd timer and stops at 15:15 IST. Install once on the server:

```bash
cd ~/orb-paper-bot && git pull origin main && bash deploy/install.sh
```

Useful: `systemctl list-timers orb-bot.timer`, `journalctl -u orb-bot -n 50 --no-pager`, `sudo systemctl stop orb-bot` (stop today's run), `sudo systemctl disable --now orb-bot.timer` (turn off). The GitHub Actions workflow is manual-only now, so two bots never trade at once.

## AI exits (optional)

By default a trade only closes at its stop, its target or the 15:15 square-off. Set `AI_EXITS` in `.env` to let Gemini watch open trades every `AI_CHECK_SECONDS` (default 300) and answer hold or exit:
- `AI_EXITS=off` (default): never asked.
- `AI_EXITS=shadow`: asked and printed in the log, never acted on.
- `AI_EXITS=act`: an "exit" answer closes the trade at market (reason `ai_exit`, the AI's sentence is saved on the trade).

The AI can only close a trade earlier. It cannot widen the stop or hold past 15:15, and if the API fails the trade is simply held.

## Auto deploy (EC2 pulls from GitHub)

A systemd timer (`orb-update.timer`) checks GitHub every 5 minutes. When `main` has new commits it pulls them (fast-forward only), installs new packages if `requirements.txt` changed, checks that the Python files compile (rolls back if not) and refreshes the dashboard files in Nginx. It never restarts the bot: the bot starts fresh each weekday 09:05 IST and uses the latest code then. No inbound SSH is needed, so port 22 can stay closed.

Install or refresh once: `cd ~/orb-paper-bot && git pull origin main && bash deploy/install.sh`. Watch it: `journalctl -u orb-update -n 20 --no-pager`. If you change files in `deploy/*.service` or `*.timer`, run `bash deploy/install.sh` again.

## Angel One live prices (optional)

Yahoo prices are about 15 minutes late. Set `DATA_SOURCE=angel` in `.env` and the bot asks Angel One for the live price of all stocks in one call every `ANGEL_POLL_SECONDS` (default 5), and builds the 9:15-9:30 opening range from those samples. It needs the bot to be running at 9:15, which the 09:05 timer does. If login fails, packages are missing, a stock's token does not match, or Angel One blocks a call, the bot silently uses Yahoo for that moment. Needs `smartapi-python` and `pyotp` in the server's venv (`pip install -r requirements-angelone-test.txt`) and these in `.env` (names are matched flexibly, see `angel_feed.py`): API key, client code, PIN, TOTP secret.

## Shadow ledger and AI control group
The baseline strategy is frozen. `shadow.py` replays each real paper trade against alternative exit rules (break-even after 1R, 50% give-back, 1R trailing stop, and the AI's shadow exit advice). A separate `no_ai_control` ledger records each eligible breakout using the original stop/target, same sizing, fees and slippage—even when `LLM_MODE=gate` rejects the real entry. Control positions continue independently after an AI-managed paper trade exits and are squared off separately. Completed control rows include the signal ID, AI decision/reason and hypothetical net P&L, and are stored in `shadow_trades`; they never alter real paper orders. Run the updated `schema.sql` in Supabase SQL Editor to add the new `shadow_trades` columns before relying on this data. Shadow writes are best-effort and do not affect the baseline. Keep AI decisions in shadow mode until the control group has enough prospective observations (at least 2-4 months) and results are reviewed; historical backtests alone are not proof of an edge. `AI_EXITS=shadow` logs exit advice but does not act on it. Angel One historical candles are checked separately from live quotes with `python angel_data.py` (one careful request; it stops on a rate block).

## Dashboard rebuild (in progress)
A new React + TypeScript app is being built in `dashboard/` with Vite, Tailwind CSS, Recharts, Lucide icons and the Supabase browser client. It includes overview metrics, trade journal, AI vs. no-AI control analytics, backtest placeholder and risk monitor. The legacy `docs/` page remains in place until the new app passes build/data checks and the Pages deployment is switched safely.

For local development, see [`dashboard/README.md`](dashboard/README.md). Configure only `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`; never put the service-role key in browser code. Without those variables, the app uses clearly labelled preview data.

## Telegram alerts and watchdog
`notify.py` sends a Telegram message for every entry, exit and halt (loss cap, missing price, database write failure). `watchdog.py` runs every 5 minutes from its own systemd timer, so it still works when the bot is dead, and alerts once if the bot is not running or an open trade's price has not updated for 10 minutes (and once more when it recovers). Without the two Telegram values in `.env` everything is a silent no-op.

Setup: in Telegram talk to @BotFather, send `/newbot`, copy the token. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read `"chat":{"id":...}`. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (never in chat), then run `bash deploy/install.sh` once to install the watchdog timer.
