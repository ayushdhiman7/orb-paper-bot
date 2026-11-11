import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardData, PaperTrade } from "../lib/api";
import { inr, pct, signedInr, tone } from "../lib/format";
import { confirmed, summarize, unrealized } from "../lib/stats";
import { TradeList } from "../components/Trades";
import { Empty, Panel, Stat, Stats } from "../components/ui";

type Props = { data: DashboardData; range: string; onExit: (t: PaperTrade) => void; exitStatus: Record<string, string> };

export default function Today({ data, range, onExit, exitStatus }: Props) {
  const closed = confirmed(data.trades);
  const s = summarize(closed);
  const open = data.openPositions;
  const mark = open.reduce((sum, t) => sum + (unrealized(t) ?? 0), 0);
  const estimated = data.trades.filter(t => t.exit_estimated).length;
  const recent = [...data.trades].filter(t => t.status !== "open")
    .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()).slice(0, 5);
  const axis = { stroke: "var(--muted)", fontSize: 11, tickLine: false, axisLine: false } as const;

  return (
    <>
      <Stats>
        <Stat label={`Realized · ${range}`} value={signedInr(s.total)} tone={tone(s.total)} sub={`${s.n} confirmed trades`} />
        <Stat label="Open mark-to-market" value={signedInr(mark)} tone={tone(mark)} sub={`${open.length} open position${open.length === 1 ? "" : "s"}`} />
        <Stat label="Win rate" value={s.n ? pct(s.winRate) : "—"} sub={s.n ? `${s.wins} wins · ${s.n - s.wins} not wins` : "no closed trades"} />
        <Stat label="Profit factor" value={s.profitFactor == null ? "—" : s.profitFactor.toFixed(2)} sub={`max drawdown ${inr(s.maxDrawdown)}`} />
      </Stats>
      {estimated > 0 && <p className="footnote">{estimated} trade{estimated === 1 ? " has an" : "s have"} an estimated exit and {estimated === 1 ? "is" : "are"} excluded from these numbers.</p>}

      <Panel title="Open positions" note="Paper positions with live marks">
        <TradeList trades={open} onExit={onExit} exitStatus={exitStatus} />
      </Panel>

      <div className="grid-2">
        <Panel title="Equity" note={`Cumulative confirmed P&L · ${range}`}>
          {s.series.length ? (
            <div className="chart"><ResponsiveContainer>
              <AreaChart data={s.series} margin={{ left: -12, right: 4, top: 8 }}>
                <defs><linearGradient id="eq" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis dataKey="day" {...axis} /><YAxis {...axis} />
                <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }} formatter={(v: number) => [inr(v, true), "Cumulative"]} />
                <Area type="monotone" dataKey="cum" stroke="var(--accent)" strokeWidth={2} fill="url(#eq)" />
              </AreaChart>
            </ResponsiveContainer></div>
          ) : <Empty title="No closed trades yet" hint="The equity curve appears after the first confirmed exit." />}
        </Panel>
        <Panel title="Daily P&L" note="Net of costs and slippage">
          {s.series.length ? (
            <div className="chart"><ResponsiveContainer>
              <BarChart data={s.series} margin={{ left: -12, right: 4, top: 8 }}>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis dataKey="day" {...axis} /><YAxis {...axis} />
                <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }} formatter={(v: number) => [inr(v, true), "Day"]} />
                <Bar dataKey="pnl" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer></div>
          ) : <Empty title="No data" />}
        </Panel>
      </div>

      <Panel title="Recent trades">
        <TradeList trades={recent} />
      </Panel>
    </>
  );
}
