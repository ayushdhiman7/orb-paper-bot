import type { PaperTrade } from "../lib/api";
import { inr, signedInr, tone } from "../lib/format";
import { confirmed, summarize, unrealized } from "../lib/stats";
import { Notice, Panel, Stat, Stats } from "../components/ui";

export default function Risk({ trades, open }: { trades: PaperTrade[]; open: PaperTrade[] }) {
  const s = summarize(confirmed(trades));
  const exposure = open.reduce((sum, t) => sum + Number(t.qty) * Number(t.last_price ?? t.entry), 0);
  const mark = open.reduce((sum, t) => sum + (unrealized(t) ?? 0), 0);
  const stale = open.filter(t => t.last_price == null).length;
  return (
    <>
      {stale > 0 && <Notice kind="error">{stale} open position{stale === 1 ? " has" : "s have"} no live price. Check the bot and the Angel feed.</Notice>}
      <Stats>
        <Stat label="Open positions" value={String(open.length)} />
        <Stat label="Marked exposure" value={inr(exposure)} />
        <Stat label="Unrealized" value={signedInr(mark)} tone={tone(mark)} />
        <Stat label="Max drawdown" value={inr(s.maxDrawdown)} sub="confirmed trades" />
      </Stats>
      <Panel title="Trade quality" note="Confirmed trades in the selected range">
        <div className="rows">
          <div><span>Average win</span><strong className="pos">{signedInr(s.avgWin)}</strong></div>
          <div><span>Average loss</span><strong className="neg">{signedInr(s.avgLoss)}</strong></div>
          <div><span>Best trade</span><strong className="pos">{signedInr(s.best)}</strong></div>
          <div><span>Worst trade</span><strong className="neg">{signedInr(s.worst)}</strong></div>
        </div>
      </Panel>
    </>
  );
}
