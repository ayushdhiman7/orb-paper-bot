-- Durable idempotency and delivery state for the Nifty 50 paper daily report.
create table if not exists public.bot_session_reports (
    session_date date primary key,
    summary jsonb not null,
    telegram_sent_at timestamptz,
    webhook_queued_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.bot_session_reports enable row level security;
