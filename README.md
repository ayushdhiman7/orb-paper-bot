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

## Deploy
The bot is a long-running worker, so it needs an always-on host.
- **Free option:** a GitHub Actions cron is awkward for a long loop; the simplest free route is running it on your own PC/laptop during market hours, or Oracle Cloud's always-free VM.
- **Paid but easy:** Render background worker (`render.yaml` included, starter plan), Railway, or Fly.io.

## Before any real money
Paper trade 4-8 weeks and check the Supabase table. Past paper results do not guarantee live results. Going live would need a broker API (Angel One SmartAPI / Upstox) and checking SEBI's current algo-trading rules. Not financial advice.
