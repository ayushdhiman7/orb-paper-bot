-- Persist AI-approved risk levels so open paper positions restore exactly after restart.
-- Existing rows remain valid; legacy positions continue using the configured fixed-risk fallback.
alter table public.paper_trades
    add column if not exists stop_price numeric,
    add column if not exists target_price numeric,
    add column if not exists ai_confidence numeric,
    add column if not exists ai_rank integer,
    add column if not exists risk_verdict text;

alter table public.paper_trades
    add constraint paper_trades_ai_confidence_range
    check (ai_confidence is null or (ai_confidence >= 0 and ai_confidence <= 1))
    not valid;

alter table public.paper_trades
    validate constraint paper_trades_ai_confidence_range;
