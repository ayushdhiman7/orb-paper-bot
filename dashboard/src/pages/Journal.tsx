import { useMemo, useState } from "react";
import type { PaperTrade } from "../lib/api";
import { sym } from "../lib/format";
import { TradeList } from "../components/Trades";
import { Panel } from "../components/ui";

export default function Journal({ trades }: { trades: PaperTrade[] }) {
  const [query, setQuery] = useState("");
  const [side, setSide] = useState("All");
  const rows = useMemo(() => [...trades]
    .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())
    .filter(t => (side === "All" || t.side === side) &&
      `${sym(t.symbol)} ${t.reason ?? ""} ${t.llm_decision ?? ""}`.toLowerCase().includes(query.toLowerCase())),
  [trades, query, side]);
  return (
    <Panel title="Trade journal" note={`${rows.length} of ${trades.length} trades`}
      action={<div className="filters">
        <input type="search" placeholder="Search symbol, reason, AI" value={query} onChange={e => setQuery(e.target.value)} />
        <select value={side} onChange={e => setSide(e.target.value)} aria-label="Side"><option>All</option><option>BUY</option><option>SELL</option></select>
      </div>}>
      <TradeList trades={rows} />
    </Panel>
  );
}
