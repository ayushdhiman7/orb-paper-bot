create table if not exists public.orb_bot_settings (
    id integer primary key check (id = 1),
    settings jsonb not null,
    version bigint not null default 1,
    updated_at timestamptz not null default now()
);

insert into public.orb_bot_settings (id, settings, version)
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

alter table public.orb_bot_settings enable row level security;
