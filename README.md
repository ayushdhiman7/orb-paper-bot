# ORB Paper Trading Bot (NSE, intraday)

Opening-range-breakout bot that trades **fake money only**. No broker connection.

## What it does
- Pulls free 1-minute NSE data from Yahoo Finance (`yfinance`, delayed ~15 min).
- Marks the 9:15-9:30 IST high/low per stock, enters on a breakout, exits on stop-loss, target, or the 3:15 PM square-off.
- Risk rules: 1% risk per trade, 3% daily loss cap, max 3 trades/day, ~Rs 20/order cost model.
- Logs every closed trade to Supabase (or `trades.csv` if no keys are set).

## Run locally
```
pip install -r requirements.txt
python bot.py
```
Run it on a weekday during market hours (9:15-15:30 IST). It sleeps otherwise.

## Supabase (free)
1. Create a project at supabase.com.
2. SQL Editor: run `schema.sql`.
3. Settings -> API: copy the project URL and the `service_role` key into env vars `SUPABASE_URL` and `SUPABASE_KEY`. Never commit the key.

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
`docs/` is a static page with four tabs: Overview (open trades with live delayed prices and open P&L), History (daily P&L bars), Stocks (per-stock stats with filters) and Backtest (latest run from Supabase).
- GitHub Pages: Settings -> Pages -> Deploy from a branch -> main -> /docs.
- Vercel: vercel.com -> Add New Project -> import this repo -> set Root Directory to `docs`, Framework "Other", no build command -> Deploy.

## Backtest
`backtest.py` replays the same rules on ~60 days of free 5-minute data with costs and slippage, tries 15 stop/target settings, and checks the best one on days it never saw. Run it from the Actions tab: backtest -> Run workflow, then open the run and read the summary. It is a smoke test, not proof of an edge.

## Before any real money
Paper trade 4-8 weeks and check the Supabase table. Past paper results do not guarantee live results. Going live would need a broker API (Angel One SmartAPI / Upstox) and checking SEBI's current algo-trading rules. Not financial advice.
