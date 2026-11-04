-- Keep the original risk distance immutable for R-based position protection.
alter table public.paper_trades
    add column if not exists initial_stop numeric;

-- Existing open rows predate the immutable field. Backfill from their current stop
-- as the safest available baseline; new Nifty 50 entries write their true initial stop.
update public.paper_trades
set initial_stop = stop
where initial_stop is null and stop is not null;
