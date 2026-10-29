import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const isSupabaseConfigured = Boolean(url && key);
export const supabase = isSupabaseConfigured ? createClient(url!, key!) : null;

export type PaperTrade = {
  id: number;
  ts: string;
  symbol: string;
  side: "BUY" | "SELL" | string;
  qty: number;
  entry: number;
  exit: number | null;
  pnl: number | null;
  reason: string | null;
  status?: "open" | "closed" | string;
  last_price?: number | null;
  last_price_ts?: string | null;
  llm_decision?: string | null;
  llm_reason?: string | null;
  exit_estimated?: boolean;
};

export type ControlTrade = {
  id: number;
  trade_id: number | null;
  signal_id?: string | null;
  symbol: string;
  variant: string;
  side?: string | null;
  qty?: number | null;
  entry_price?: number | null;
  entry_fee?: number | null;
  exit_price: number | null;
  exit_reason: string | null;
  ai_decision?: string | null;
  ai_reason?: string | null;
  pnl: number | null;
  baseline_pnl: number | null;
  ts: string;
  entry_ts?: string | null;
};

export type BacktestRun = {
  id: number;
  created_at: string;
  summary_md: string | null;
  result: Record<string, any>;
};

export async function loadDashboardData() {
  if (!supabase) throw new Error("Supabase is not configured.");
  const [trades, controls, backtests] = await Promise.all([
    supabase.from("paper_trades").select("*").order("ts", { ascending: false }).limit(500),
    supabase.from("shadow_trades").select("*").eq("variant", "no_ai_control").order("ts", { ascending: false }).limit(1000),
    supabase.from("backtest_runs").select("id,created_at,summary_md,result").order("created_at", { ascending: false }).limit(50),
  ]);
  if (trades.error) throw new Error(trades.error.message);
  if (controls.error) throw new Error(controls.error.message);
  if (backtests.error) throw new Error(`Backtest data unavailable: ${backtests.error.message}`);
  return {
    trades: (trades.data ?? []) as PaperTrade[],
    controls: (controls.data ?? []) as ControlTrade[],
    backtests: (backtests.data ?? []) as BacktestRun[],
  };
}