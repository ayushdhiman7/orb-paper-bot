-- The dashboard and bot access these tables only through the server-side service_role key.
-- No browser/client role should read or mutate trading, settings, exit-request, or report data.
revoke all privileges on table
    public.paper_trades,
    public.shadow_trades,
    public.backtest_runs,
    public.manual_exit_requests,
    public.orb_bot_settings,
    public.bot_session_reports
from public, anon, authenticated;

-- Remove the legacy anonymous read path explicitly; RLS remains enabled.
drop policy if exists "public read shadow_trades" on public.shadow_trades;
