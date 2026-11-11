import type { ControlTrade, PaperTrade } from "../lib/api";
import { inr, pct, signedInr, sym, tone, when } from "../lib/format";
import { confirmed } from "../lib/stats";
import { Badge, Empty, Notice, Panel, Stat, Stats } from "../components/ui";

const LABEL: Record<string, string> = {
  no_ai_control: "No-AI control", breakeven_1R: "Breakeven at 1R", giveback_50: "Give back 50%",
  trail_1R: "Trail from 1R", ai_exit: "AI exit advice",
};

export default function Compare({ trades, controls }: { trades: PaperTrade[]; controls: ControlTrade[] }) {
  const real = new Map(confirmed(trades).map(t => [String(t.id), t]));
  const done = controls.filter(c => c.pnl != null && c.trade_id != null && real.has(String(c.trade_id)));
  const variants = [...new Set(done.map(c => c.variant))];
  const rows = variants.map(v => {
    const set = done.filter(c => c.variant === v);
    const total = set.reduce((s, c) => s + Number(c.pnl), 0);
    const base = set.reduce((s, c) => s + Number(real.get(String(c.trade_id))!.pnl), 0);
    return { variant: v, n: set.length, total, base, delta: total - base, wins: set.filter(c => Number(c.pnl) > 0).length };
  }).sort((a, b) => b.delta - a.delta);

  const decisions = trades.reduce<Record<string, number>>((acc, t) => { const k = t.llm_decision ?? "none"; acc[k] = (acc[k] ?? 0) + 1; return acc; }, {});
  const control = done.filter(c => c.variant === "no_ai_control").sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());

  return (
    <>
      <Notice>Alternative exits are <strong>log-only</strong>. Each row compares what a rule would have made on the same real trades. Small samples prove nothing, so wait for 2–4 months before changing any policy.</Notice>
      <Stats>
        <Stat label="Matched trades" value={String(real.size)} sub="confirmed, with shadow rows" />
        <Stat label="AI said take" value={String(decisions.take ?? 0)} />
        <Stat label="AI said skip" value={String(decisions.skip ?? 0)} />
        <Stat label="No AI opinion" value={String(decisions.none ?? 0)} />
      </Stats>
      <Panel title="Exit variants vs baseline" note="Same trades, different exit rule · INR">
        {rows.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Variant</th><th>Trades</th><th>Win rate</th><th>Variant P&L</th><th>Baseline</th><th>Difference</th></tr></thead>
            <tbody>{rows.map(r => (
              <tr key={r.variant}>
                <td>{LABEL[r.variant] ?? r.variant}</td><td>{r.n}</td><td>{pct(r.wins / r.n * 100, 0)}</td>
                <td className={tone(r.total)}>{signedInr(r.total)}</td><td>{inr(r.base, true)}</td>
                <td className={tone(r.delta)}><strong>{signedInr(r.delta)}</strong></td>
              </tr>))}</tbody>
          </table></div>
        ) : <Empty title="No shadow results yet" hint="Rows appear after the first confirmed trade closes." />}
      </Panel>
      <Panel title="No-AI control" note="What the same signal would have made without any AI input">
        {control.length ? (
          <ul className="plain-list">{control.map(c => (
            <li key={c.id}><span><strong>{sym(c.symbol)}</strong> <small>{when(c.ts)}</small></span>
              <span>{c.ai_decision && <Badge kind={c.ai_decision === "take" ? "take" : "skip"}>AI {c.ai_decision}</Badge>} <b className={tone(c.pnl)}>{signedInr(Number(c.pnl))}</b></span></li>
          ))}</ul>
        ) : <Empty title="No control rows yet" />}
      </Panel>
    </>
  );
}
