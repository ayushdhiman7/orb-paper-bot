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

-- Added later: live price of open trades, open/closed status, and saved backtest runs
alter table paper_trades alter column exit drop not null;
alter table paper_trades alter column pnl drop not null;
alter table paper_trades add column if not exists status text not null default 'closed';
alter table paper_trades add column if not exists last_price numeric;
alter table paper_trades add column if not exists last_price_ts timestamptz;
alter table paper_trades add column if not exists llm_decision text;
alter table paper_trades add column if not exists llm_reason text;
create policy "public read paper_trades" on paper_trades for select to anon using (true);

create table if not exists backtest_runs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  summary_md text,
  result jsonb not null
);
alter table backtest_runs enable row level security;
create policy "public read backtest_runs" on backtest_runs for select to anon using (true);

-- The static dashboard reads these tables with the publishable/anon key.
grant select on table paper_trades, backtest_runs to anon;
