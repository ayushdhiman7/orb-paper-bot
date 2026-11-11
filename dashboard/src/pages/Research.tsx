import { useCallback, useEffect, useState } from "react";
import { loadResearch } from "../lib/api";
import { inr, when } from "../lib/format";
import { Empty, Notice, Panel, Stat, Stats } from "../components/ui";

export default function Research() {
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    loadResearch().then(setReport).catch(e => setError(e instanceof Error ? e.message : "Unable to load the report."));
  }, []);
  useEffect(load, [load]);

  if (error) return <Notice kind="error" action={<button className="btn" onClick={load}>Retry</button>}>{error}</Notice>;
  if (!report) return <p className="footnote">Loading research report…</p>;
  const coverage = report.coverage ?? {};
  const candidates: any[] = Array.isArray(report.candidates) ? report.candidates : [];
  return (
    <>
      <Notice>Research only. This scanner never places orders and does not change the Nifty 50 strategy.</Notice>
      <Stats>
        <Stat label="Status" value={String(report.status ?? "unknown")} sub={report.generated_at ? when(report.generated_at) : undefined} />
        <Stat label="Fresh quotes" value={`${coverage.fresh_quotes ?? 0} / ${coverage.instruments ?? 0}`} />
        <Stat label="Liquidity checked" value={String(coverage.liquidity_values ?? 0)} />
        <Stat label="Eligible" value={String(candidates.length)} />
      </Stats>
      <Panel title="Eligible stocks" note={`Under ₹${report.criteria?.max_price_inr ?? 25}, spread and 20-session liquidity passed`}>
        {candidates.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Symbol</th><th>Price</th><th>Spread</th><th>Avg daily value</th></tr></thead>
            <tbody>{candidates.map((c, i) => (
              <tr key={c.symbol ?? i}>
                <td><strong>{c.symbol}</strong></td><td>₹{Number(c.price ?? c.last_price ?? 0).toFixed(2)}</td>
                <td>{c.spread_pct != null ? `${Number(c.spread_pct).toFixed(2)}%` : "—"}</td>
                <td>{c.avg_daily_traded_value_inr != null ? inr(Number(c.avg_daily_traded_value_inr)) : "—"}</td>
              </tr>))}</tbody>
          </table></div>
        ) : <Empty title="No eligible stocks" />}
      </Panel>
    </>
  );
}
