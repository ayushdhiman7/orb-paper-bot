-- Run this once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run
create table if not exists paper_trades (
  id bigint generated always as identity primary key,
  ts timestamptz not null,
  symbol text not null,
  side text not null,
  qty int not null,
  entry numeric not null,
  exit numeric not null,
  pnl numeric not null,
  reason text,
  mode text default 'paper'
);

-- Keep the table private; the bot uses the service_role key which bypasses RLS.
alter table paper_trades enable row level security;
