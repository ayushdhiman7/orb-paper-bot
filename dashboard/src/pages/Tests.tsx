import type { BacktestRun } from "../lib/api";
import { inr, when } from "../lib/format";
import { Empty, Panel, Stat, Stats } from "../components/ui";

export default function Tests({ runs }: { runs: BacktestRun[] }) {
  const latest = runs[0];
  const base = latest?.result?.baseline;
  const test = latest?.result?.test;
  if (!latest) return <Panel title="Backtests"><Empty title="No saved backtests" hint="Run the backtest workflow to record one." /></Panel>;
  return (
    <>
      <Stats>
        <Stat label="Saved runs" value={String(runs.length)} />
        <Stat label="Baseline P&L" value={base?.total == null ? "—" : inr(Number(base.total))} sub={base?.n != null ? `${base.n} trades` : undefined} />
        <Stat label="Out-of-sample" value={test?.total == null ? "—" : inr(Number(test.total))} sub={test?.n != null ? `${test.n} trades` : undefined} />
        <Stat label="Verdict" value={base?.verdict ? (String(base.verdict).startsWith("REJECT") ? "Reject" : "Review") : "—"} />
      </Stats>
      <Panel title="Latest run" note={`#${latest.id} · ${when(latest.created_at)}`}>
        {latest.summary_md ? <pre className="summary">{latest.summary_md}</pre> : <Empty title="No summary text" />}
      </Panel>
    </>
  );
}
