-- Authenticated requests from the dashboard to close an existing paper position.
-- The bot is the only component that executes the close using a fresh market quote.
create table if not exists public.manual_exit_requests (
    id bigint generated always as identity primary key,
    trade_id bigint not null,
    requested_at timestamptz not null default now(),
    status text not null default 'pending'
        check (status in ('pending', 'executed', 'rejected')),
    processed_at timestamptz,
    result_reason text
);

create index if not exists manual_exit_requests_pending_idx
    on public.manual_exit_requests (status, requested_at)
    where status = 'pending';

alter table public.manual_exit_requests enable row level security;

-- No client policies: requests are created/read only by the server-side API and bot.
