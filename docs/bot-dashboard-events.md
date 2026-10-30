# Bot-to-dashboard events

## Event flow

The bot writes its paper-trade row to Supabase first. Only after that write succeeds,
it appends a lifecycle event to a local JSONL outbox. A background worker delivers
the event to the dashboard API with an HMAC-SHA256 signature. Delivery failures are
retried with exponential backoff; they do not alter trade state or broker behavior.

The API deduplicates by `event_id` in `public.dashboard_events`. Webhook timestamps must be timezone-aware ISO-8601 values, and signatures must use the `sha256=` HMAC-SHA256 header format. The React dashboard
uses Server-Sent Events as a notification channel. On connection, the API sends a `ready` event with the initial database cursor; the dashboard refreshes authoritative data at that boundary, then reloads data from
`/api/dashboard`. SSE reconnects resume using `Last-Event-ID`; while disconnected,
the dashboard falls back to a 30-second refresh.

## Events

- `trade.opened`: emitted after the open row is confirmed in `paper_trades`.
- `trade.closed`: emitted after the close update is confirmed in `paper_trades`.

No price-tick events are emitted. The event stream is not an order interface.

## Required environment

Set the same high-entropy random secret on the bot and API. Do not commit it.

Bot/API environment:
```dotenv
DASHBOARD_WEBHOOK_SECRET=<same-random-secret-on-both-processes>
```

Bot only:
```dotenv
DASHBOARD_WEBHOOK_URL=https://orb7.duckdns.org/api/events
# Optional; default is <bot-repo>/var/webhook-outbox.jsonl
# WEBHOOK_OUTBOX_PATH=/home/ubuntu/orb-paper-bot/var/webhook-outbox.jsonl
```

The current API loads `/home/ubuntu/orb-paper-bot/.env`, so the API secret can
use that existing environment file. Never put the secret in the React app.

## Database migration

Apply `supabase/migrations/202610300001_dashboard_events.sql` to the intended
Supabase project before enabling webhook delivery. This PR only adds the migration
file; it does not execute it. RLS is enabled with no client policies: access is
server-side only through the dashboard API service key.

## Nginx SSE proxy

In the existing `location /api/` block, add:

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 1h;
proxy_send_timeout 1h;
```

Keep the existing proxy headers and upstream. Validate with `sudo nginx -t`
before any reload. Do not restart the bot to apply an API/Nginx-only change.

## Safe rollout order

1. Apply the database migration.
2. Configure the same webhook secret in the API and bot environments.
3. Add the Nginx SSE directives and validate the config.
4. Deploy the updated API and verify `/health`, webhook auth rejection, and SSE.
5. Deploy the bot sender only after the API is ready.
6. Confirm one paper entry/exit event end-to-end. Never generate test broker orders.

The existing EC2 API is a separate non-Git working directory and was observed to be
older than GitHub `main`. It must be backed up and upgraded as a separate deployment
step; do not blindly overwrite it or kill the current Uvicorn process.
