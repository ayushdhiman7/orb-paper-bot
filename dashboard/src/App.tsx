import { useCallback, useState } from "react";
import { requestManualExit } from "./lib/api";
import type { DashboardRange, PaperTrade } from "./lib/api";
import { useDashboard } from "./lib/useDashboard";
import { ExitModal } from "./components/ExitModal";
import { Notice } from "./components/ui";
import Today from "./pages/Today";
import Journal from "./pages/Journal";
import Compare from "./pages/Compare";
import Tests from "./pages/Tests";
import Risk from "./pages/Risk";
import Research from "./pages/Research";
import Settings from "./pages/Settings";

const TABS = ["Today", "Trades", "Compare", "Risk", "Tests", "Research", "Settings"] as const;
type Tab = (typeof TABS)[number];
const RANGES: DashboardRange[] = ["1D", "7D", "30D", "ALL"];
const DATA_TABS: Tab[] = ["Today", "Trades", "Compare", "Risk", "Tests"];

export default function App() {
  const [tab, setTab] = useState<Tab>("Today");
  const [range, setRange] = useState<DashboardRange>("7D");
  const { data, loading, error, live, refresh } = useDashboard(range);
  const [exitTrade, setExitTrade] = useState<PaperTrade | null>(null);
  const [exitStatus, setExitStatus] = useState<Record<string, string>>({});

  const confirmExit = useCallback(async (token: string) => {
    if (!exitTrade) return;
    const key = String(exitTrade.id);
    setExitStatus(s => ({ ...s, [key]: "Submitting…" }));
    setExitTrade(null);
    try {
      const r = await requestManualExit(key, token);
      setExitStatus(s => ({ ...s, [key]: `Exit queued · request #${r.request_id}` }));
    } catch (e) {
      setExitStatus(s => ({ ...s, [key]: e instanceof Error ? `Failed · ${e.message}` : "Exit request failed" }));
    }
  }, [exitTrade]);

  const needsData = DATA_TABS.includes(tab);
  return (
    <div className="shell">
      <header className="top">
        <div className="brand"><b>ORB</b><span>v2</span><i className={`dot ${live ? "live" : ""}`} title={live ? "Live updates connected" : "Live updates disconnected"} /></div>
        {needsData && (
          <div className="seg" role="group" aria-label="Range">
            {RANGES.map(r => <button key={r} className={r === range ? "on" : ""} onClick={() => setRange(r)}>{r}</button>)}
          </div>
        )}
      </header>

      <nav className="nav" aria-label="Main">
        {TABS.map(t => <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </nav>

      <main className="page">
        <h1>{tab}</h1>
        {needsData && error && <Notice kind="error" action={<button className="btn" onClick={() => void refresh()}>Retry</button>}>{error}</Notice>}
        {needsData && loading && !error && <p className="footnote">Loading…</p>}
        {(!needsData || (!loading && !error)) && (
          <>
            {tab === "Today" && <Today data={data} range={range} onExit={setExitTrade} exitStatus={exitStatus} />}
            {tab === "Trades" && <Journal trades={data.trades} />}
            {tab === "Compare" && <Compare trades={data.trades} controls={data.controls} />}
            {tab === "Risk" && <Risk trades={data.trades} open={data.openPositions} />}
            {tab === "Tests" && <Tests runs={data.backtests} />}
            {tab === "Research" && <Research />}
            {tab === "Settings" && <Settings />}
          </>
        )}
        <footer className="foot">Paper trading only · no broker orders · ORB v2</footer>
      </main>
      {exitTrade && <ExitModal trade={exitTrade} onCancel={() => setExitTrade(null)} onConfirm={t => void confirmExit(t)} />}
    </div>
  );
}
