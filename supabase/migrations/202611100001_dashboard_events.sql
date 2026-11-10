-- Additive: create the durable dashboard event log if missing (it was never applied)
-- and allow session.summary, which the bot emits and the API accepts.
create table if not exists public.dashboard_events (
    id bigint generated always as identity primary key,
    event_id text not null unique,
    event_type text not null,
    occurred_at timestamptz not null,
    source text not null default 'orb-paper-bot',
    data jsonb not null default '{}'::jsonb,
    received_at timestamptz not null default now()
);

alter table public.dashboard_events drop constraint if exists dashboard_events_event_type_check;
alter table public.dashboard_events add constraint dashboard_events_event_type_check check (
    event_type in ('trade.opened', 'trade.closed', 'bot.status_changed', 'risk.alert', 'session.summary')
);

create index if not exists dashboard_events_received_at_idx
    on public.dashboard_events (received_at);

alter table public.dashboard_events enable row level security;
-- No client policies: only the server-side dashboard API service key can access this table.
