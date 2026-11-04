-- Additive migration for paper-only AI stop/target restoration.
alter table public.paper_trades add column if not exists stop numeric;
alter table public.paper_trades add column if not exists initial_stop numeric;
alter table public.paper_trades add column if not exists target numeric;
alter table public.paper_trades add column if not exists ai_confidence numeric;
alter table public.paper_trades add column if not exists ai_rank integer;
