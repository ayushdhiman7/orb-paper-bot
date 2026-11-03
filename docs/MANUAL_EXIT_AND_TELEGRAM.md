# Manual paper exits and Telegram alerts

## Manual exit flow

The dashboard shows an **Exit trade** control on each currently open paper trade.
The operator confirms the action and enters the dashboard control token. The API
validates the token and queues a row in `manual_exit_requests`. It does not close
the trade itself and does not call a broker.

During NSE market hours, the bot reads pending requests and matches the requested
paper-trade ID to its restored in-memory position. It requires a fresh, valid Angel One WebSocket/quote-feed tick (maximum age 45 seconds).
It deliberately does not use the bot's Yahoo fallback for manual exits because those
candles can be delayed. If Angel One is unavailable, the request remains pending.
It then uses the existing `close_position` path so adverse slippage, fees, Supabase
trade persistence, shadow-ledger handling and dashboard lifecycle events remain
consistent. A request with no fresh quote remains pending. A request for a trade
that is no longer open is rejected. If the bot is stopped, requests remain pending
until it next runs during market hours.

## Required setup

Apply `supabase/migrations/202611030001_manual_exit_requests.sql` to the same
Supabase project used by the bot and dashboard API.

Generate a strong token (for example, `openssl rand -hex 32`) and add it to the existing EC2 bot `.env` file:

```dotenv
DASHBOARD_CONTROL_TOKEN=<long-random-secret>
```

The dashboard API already loads that environment file from
`/home/ubuntu/orb-paper-bot/.env`. Restart/reload the dashboard API only after
the migration and environment value are configured. Do not put this token in the
React build, source control, or browser local storage. The dashboard prompts for
it when an operator requests an exit.

## Telegram formatting

Telegram messages receive category emojis for startup, BUY/SELL entries, exits,
halts, risk alerts, AI notes and generic notifications. Emoji formatting does not
change the underlying alert text or trading decisions.

## Safety

- Paper positions only; no broker order API is called.
- Manual exit requires a confirmation click and server-side bearer-token check.
- Bot is the only component that executes a close.
- Manual exits require a fresh Angel One quote (45-second maximum age); Yahoo fallback is not accepted.
- Existing fees/slippage are preserved.
- This feature does not deploy itself. Apply the database migration and configure
  the secret as a separately approved deployment step.
