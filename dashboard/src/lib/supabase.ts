const apiBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export const isApiConfigured = Boolean(apiBase);

export type PaperTrade = {
  id: number | string; ts: string; symbol: string; side: string; qty: number;
  entry: number; exit: number | null; pnl: number | null; reason: string | null;
  status?: string; last_price?: number | null; last_price_ts?: string | null;
  llm_decision?: string | null; llm_reason?: string | null; exit_estimated?: boolean;
};
export type ControlTrade = {
  id: number | string; trade_id: number | string | null; signal_id?: string | null;
  symbol: string; variant: string; side?: string | null; qty?: number | null;
  entry_price?: number | null; entry_fee?: number | null; exit_price: number | null;
  exit_reason: string | null; ai_decision?: string | null; ai_reason?: string | null;
  pnl: number | null; baseline_pnl: number | null; ts: string; entry_ts?: string | null;
};
export type BacktestRun = {
  id: number | string; created_at: string; summary_md: string | null;
  result: Record<string, unknown>;
};
export type DashboardData = { trades: PaperTrade[]; controls: ControlTrade[]; backtests: BacktestRun[] };

export async function loadDashboardData(): Promise<DashboardData> {
  if (!apiBase) throw new Error("Backend API is not configured. Set VITE_API_BASE_URL.");
  const response = await fetch(`${apiBase}/api/dashboard`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) throw new Error(`Dashboard API returned HTTP ${response.status}.`);
  const payload: unknown = await response.json();
  if (!payload || typeof payload !== "object") throw new Error("Dashboard API returned an invalid response.");
  const data = payload as Record<string, unknown>;
  if (!Array.isArray(data.trades) || !Array.isArray(data.controls) || !Array.isArray(data.backtests)) {
    throw new Error("Dashboard API must return trades, controls, and backtests arrays.");
  }
  return {
    trades: data.trades as PaperTrade[],
    controls: data.controls as ControlTrade[],
    backtests: data.backtests as BacktestRun[],
  };
}
