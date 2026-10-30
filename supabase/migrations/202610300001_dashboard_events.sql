-- Durable, deduplicated bot-to-dashboard event log.
create table if not exists public.dashboard_events (
    id bigint generated always as identity primary key,
    event_id text not null unique,
    event_type text not null check (
        event_type in ('trade.opened', 'trade.closed', 'bot.status_changed', 'risk.alert')
    ),
    occurred_at timestamptz not null,
    source text not null default 'orb-paper-bot',
    data jsonb not null default '{}'::jsonb,
    received_at timestamptz not null default now()
);

create index if not exists dashboard_events_received_at_idx
    on public.dashboard_events (received_at);

alter table public.dashboard_events enable row level security;

-- No client policies: only the server-side dashboard API service key can access this table.
