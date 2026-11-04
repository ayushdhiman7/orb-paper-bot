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

-- Estimated/reconstructed exits are kept for audit but excluded from confirmed performance metrics.
alter table paper_trades add column if not exists exit_estimated boolean not null default false;
alter table paper_trades add column if not exists exit_source text;

-- Shadow ledger: hypothetical outcomes of alternative exit rules, per real paper trade. Research only.
create table if not exists shadow_trades (
  id bigint generated always as identity primary key,
  trade_id bigint, symbol text, variant text, exit_price numeric, exit_reason text,
  pnl numeric, baseline_pnl numeric, ts timestamptz
);
-- Independent no-AI control records, including signals the AI rejected and controls that outlive AI exits.
alter table shadow_trades add column if not exists signal_id text;
alter table shadow_trades add column if not exists side text;
alter table shadow_trades add column if not exists qty integer;
alter table shadow_trades add column if not exists entry_price numeric;
alter table shadow_trades add column if not exists entry_fee numeric;
alter table shadow_trades add column if not exists entry_ts timestamptz;
alter table shadow_trades add column if not exists ai_decision text;
alter table shadow_trades add column if not exists ai_reason text;
alter table shadow_trades enable row level security;
create policy "public read shadow_trades" on shadow_trades for select to anon using (true);
grant select on table shadow_trades to anon;


-- Nifty 50 paper runner: persisted AI levels and immutable initial risk.
alter table paper_trades add column if not exists stop numeric;
alter table paper_trades add column if not exists initial_stop numeric;
alter table paper_trades add column if not exists target numeric;
alter table paper_trades add column if not exists ai_confidence numeric;
alter table paper_trades add column if not exists ai_rank integer;

-- Dashboard manual exits are requests only; the paper runner executes at a fresh quote.
create table if not exists manual_exit_requests (
  id bigint generated always as identity primary key,
  trade_id bigint not null,
  requested_at timestamptz not null default now(),
  status text not null default 'pending' check (status in ('pending', 'executed', 'rejected')),
  processed_at timestamptz,
  result_reason text
);
create index if not exists manual_exit_requests_pending_idx
  on manual_exit_requests (status, requested_at) where status = 'pending';
alter table manual_exit_requests enable row level security;

-- Versioned, server-side runtime settings; paper_only is permanently true.
create table if not exists orb_bot_settings (
  id integer primary key check (id = 1),
  settings jsonb not null,
  version bigint not null default 1,
  updated_at timestamptz not null default now()
);
insert into orb_bot_settings (id, settings, version)
values (1, '{
  "scan_interval_seconds": 180,
  "position_review_seconds": 300,
  "risk_per_trade_pct": 1.0,
  "daily_loss_cap_pct": 2.0,
  "max_open_positions": 2,
  "max_trades_per_day": 3,
  "breakeven_r": 1.0,
  "profit_protection_r": 1.5,
  "protected_profit_r": 0.5,
  "trailing_start_r": 2.0,
  "square_off_time": "15:15",
  "stale_quote_seconds": 45,
  "ai_position_min_confidence": 0.0,
  "emergency_stop": false,
  "sentiment_enabled": false,
  "ai_position_management_enabled": true,
  "paper_only": true
}'::jsonb, 1)
on conflict (id) do nothing;
alter table orb_bot_settings enable row level security;
