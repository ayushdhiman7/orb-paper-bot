-- Persist the exact deterministic paper-execution levels selected by the
-- Nifty 50 batch runtime. Additive only; existing rows remain valid.
-- Apply this migration before enabling ORB_RUNTIME_MODE=nifty50_batch.

alter table public.paper_trades
    add column if not exists planned_stop numeric,
    add column if not exists planned_target numeric,
    add column if not exists ai_confidence numeric,
    add column if not exists ai_rank integer,
    add column if not exists risk_verdict text;

alter table public.paper_trades
    add constraint paper_trades_ai_confidence_range
    check (ai_confidence is null or (ai_confidence >= 0 and ai_confidence <= 1))
    not valid;

alter table public.paper_trades
    validate constraint paper_trades_ai_confidence_range;
