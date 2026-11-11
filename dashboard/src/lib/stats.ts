import type { PaperTrade } from "./api";
import { day } from "./format";

export const isOpen = (t: PaperTrade) => t.status === "open";

/** Closed trades with an observed exit. Estimated/reconstructed exits are excluded from confirmed metrics. */
export const confirmed = (trades: PaperTrade[]) =>
  trades.filter(t => !isOpen(t) && t.pnl != null && !t.exit_estimated);

export function unrealized(t: PaperTrade): number | null {
  if (!isOpen(t) || t.last_price == null) return null;
  const direction = t.side === "BUY" ? 1 : -1;
  return (Number(t.last_price) - Number(t.entry)) * Number(t.qty) * direction;
}

export type Summary = {
  n: number; total: number; wins: number; winRate: number; avgWin: number; avgLoss: number;
  profitFactor: number | null; maxDrawdown: number; best: number; worst: number;
  series: { day: string; pnl: number; cum: number }[];
};

export function summarize(trades: PaperTrade[]): Summary {
  const rows = [...trades].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
  const pnls = rows.map(t => Number(t.pnl ?? 0));
  const wins = pnls.filter(p => p > 0);
  const losses = pnls.filter(p => p < 0);
  const grossWin = wins.reduce((s, p) => s + p, 0);
  const grossLoss = Math.abs(losses.reduce((s, p) => s + p, 0));
  let cum = 0, peak = 0, maxDrawdown = 0;
  const perDay = new Map<string, number>();
  rows.forEach((t, i) => {
    cum += pnls[i];
    peak = Math.max(peak, cum);
    maxDrawdown = Math.max(maxDrawdown, peak - cum);
    perDay.set(day(t.ts), cum);
  });
  let previous = 0;
  const series = [...perDay.entries()].map(([d, c]) => { const row = { day: d, pnl: c - previous, cum: c }; previous = c; return row; });
  return {
    n: rows.length, total: cum, wins: wins.length, winRate: rows.length ? wins.length / rows.length * 100 : 0,
    avgWin: wins.length ? grossWin / wins.length : 0, avgLoss: losses.length ? -grossLoss / losses.length : 0,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : null, maxDrawdown,
    best: pnls.length ? Math.max(...pnls) : 0, worst: pnls.length ? Math.min(...pnls) : 0, series,
  };
}
