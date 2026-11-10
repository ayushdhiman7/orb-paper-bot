import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, Bell, Bot, CalendarDays,
  CheckCircle2, ChevronDown, CircleHelp, Clock3, Database, Download,
  LayoutDashboard, ListFilter, Menu, RefreshCw, Search, Settings2, ShieldCheck,
  Sparkles, TrendingUp, Wallet, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { loadDashboardData, requestManualExit, loadBotSettings, saveBotSettings } from "./lib/supabase";
import type { BacktestRun, ControlTrade, DashboardRange, PaperTrade, BotSettings } from "./lib/supabase";

type Tab = "Overview" | "Trade journal" | "AI vs no-AI" | "Backtests" | "Risk monitor" | "Under-₹25 research" | "Settings";
type DashboardData = { trades: PaperTrade[]; openPositions: PaperTrade[]; controls: ControlTrade[]; backtests: BacktestRun[]; backtestsError?: string | null };

const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
const preciseMoney = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);
const formatDate = (value: string) => new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
function App() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [data, setData] = useState<DashboardData>({ trades: [], openPositions: [], controls: [], backtests: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const [query, setQuery] = useState("");
  const [sideFilter, setSideFilter] = useState("All sides");
  const [activeRange, setActiveRange] = useState<DashboardRange>("7D");
  const [mobileNav, setMobileNav] = useState(false);
  const [streamConnected, setStreamConnected] = useState(false);
  const [manualExitStatus, setManualExitStatus] = useState<Record<string, string>>({});
  const [manualExitTrade, setManualExitTrade] = useState<PaperTrade | null>(null);
  const [manualExitToken, setManualExitToken] = useState("");

  const refresh = useCallback(async (range: DashboardRange) => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const fresh = await loadDashboardData(range);
      if (currentRequest === requestId.current) setData(fresh);
    } catch (e) {
      if (currentRequest === requestId.current) {
        setError(e instanceof Error ? e.message : "Could not load dashboard data.");
      }
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(activeRange);
    return () => {
      requestId.current += 1;
    };
  }, [refresh, activeRange]);

  // Webhook -> API -> SSE is the only automatic update path. EventSource
  // reconnects natively; never poll the dashboard API as a fallback.
  useEffect(() => {
    const source = new EventSource("/api/events/stream");
    const onReady = () => {
      setStreamConnected(true);
      void refresh(activeRange);
    };
    const onTradeEvent = () => void refresh(activeRange);
    const onResync = () => void refresh(activeRange);
    source.onopen = () => setStreamConnected(true);
    source.onerror = () => setStreamConnected(false);
    source.addEventListener("ready", onReady);
    source.addEventListener("trade.opened", onTradeEvent);
    source.addEventListener("trade.closed", onTradeEvent);
    source.addEventListener("bot.status_changed", onTradeEvent);
    source.addEventListener("risk.alert", onTradeEvent);
    source.addEventListener("session.summary", onTradeEvent);
    source.addEventListener("resync", onResync);
    return () => source.close();
  }, [refresh, activeRange]);

  const handleManualExit = useCallback((trade: PaperTrade) => {
    const symbol = trade.symbol.replace(".NS", "");
    if (!window.confirm("Request a manual paper exit for " + symbol + "? The bot will close it at the next fresh market price. This does not send a broker order.")) return;
    setManualExitToken("");
    setManualExitTrade(trade);
  }, []);

  const submitManualExit = useCallback(async () => {
    if (!manualExitTrade || !manualExitToken.trim()) return;
    const key = String(manualExitTrade.id);
    setManualExitStatus(current => ({ ...current, [key]: "Submitting…" }));
    try {
      const result = await requestManualExit(manualExitTrade.id, manualExitToken.trim());
      setManualExitStatus(current => ({ ...current, [key]: "Exit queued · request #" + result.request_id }));
      setManualExitTrade(null);
      setManualExitToken("");
    } catch (e) {
      setManualExitToken("");
      setManualExitStatus(current => ({ ...current, [key]: e instanceof Error ? "Failed · " + e.message : "Exit request failed" }));
    }
  }, [manualExitTrade, manualExitToken]);
  const closedTrades = data.trades.filter(
    t => t.status !== "open" && t.pnl !== null && !t.exit_estimated,
  );
  const totalPnl = closedTrades.reduce((sum, t) => sum + Number(t.pnl ?? 0), 0);
  const winners = closedTrades.filter(t => Number(t.pnl) > 0).length;
  const winRate = closedTrades.length ? winners / closedTrades.length * 100 : 0;
  const openTrades = data.openPositions ?? data.trades.filter(t => t.status === "open");
  const unrealizedPnl = openTrades.reduce((sum, t) => sum + ((getTradePnl(t).value ?? 0)), 0);
  const recentTrades = useMemo(() => (
    [...data.trades]
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())
      .slice(0, 5)
  ), [data.trades]);
  const controlTrades = data.controls.filter(t => t.pnl !== null);
  const tradeById = new Map(closedTrades.map(t => [String(t.id), t]));
  const matchedControls = controlTrades.filter(c => c.trade_id != null && c.pnl != null && tradeById.has(String(c.trade_id)) && tradeById.get(String(c.trade_id))?.pnl != null && !tradeById.get(String(c.trade_id))?.exit_estimated);
  const matchedTradeIds = new Set(matchedControls.map(c => String(c.trade_id)));
  const matchedTrades = closedTrades.filter(t => matchedTradeIds.has(String(t.id)));
  const controlPnl = matchedControls.reduce((sum, t) => sum + Number(t.pnl ?? 0), 0);
  const matchedAiPnl = matchedTrades.reduce((sum, t) => sum + Number(t.pnl ?? 0), 0);
  const aiSkipped = data.trades.filter(t => t.llm_decision === "skip").length;
  const filteredTrades = data.trades.filter(t =>
    (sideFilter === "All sides" || t.side === sideFilter) &&
    [t.symbol, t.reason ?? "", t.llm_decision ?? ""].some(v => v.toLowerCase().includes(query.toLowerCase())),
  );

  const equity = useMemo(() => {
    const ordered = [...closedTrades].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
    let total = 0;
    const byDay = new Map<string, number>();
    for (const trade of ordered) {
      total += Number(trade.pnl ?? 0);
      const day = new Date(trade.ts).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
      byDay.set(day, total);
    }
    return [...byDay.entries()].map(([day, pnl]) => ({ day, pnl }));
  }, [closedTrades]);

  const navItems: { label: Tab; icon: typeof LayoutDashboard; hint: string; short: string }[] = [
    { label: "Overview", icon: LayoutDashboard, hint: "Performance snapshot" , short: "Overview" },
    { label: "Trade journal", icon: ListFilter, hint: "Entries & exits" , short: "Journal" },
    { label: "AI vs no-AI", icon: Bot, hint: "Control group" , short: "AI" },
    { label: "Backtests", icon: BarChart3, hint: "Strategy research" , short: "Tests" },
    { label: "Risk monitor", icon: ShieldCheck, hint: "Exposure & limits" , short: "Risk" },
    { label: "Under-₹25 research", icon: TrendingUp, hint: "Separate research universe", short: "Under ₹25" },
  ];

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="brand"><div className="brand-mark"><Activity size={20}/></div><div><strong>ORB<span>TERMINAL</span></strong><small>Paper trading workspace</small></div><button className="icon-button mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={18}/></button></div>
      <div className="workspace-label">WORKSPACE</div>
      <div className="workspace-switch"><div className="workspace-avatar">P</div><div className="workspace-copy"><strong>Paper account</strong><span>NSE · Intraday</span></div><ChevronDown size={15}/></div>
      <div className="nav-caption">ANALYTICS</div>
      <nav>{navItems.map(item => <button key={item.label} className={`nav-item ${tab === item.label ? "active" : ""}`} onClick={() => { setTab(item.label); setMobileNav(false); }}><item.icon size={18}/><span>{item.label}</span>{item.label === "AI vs no-AI" && <span className="nav-new">NEW</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="safe-card"><div className="safe-icon"><ShieldCheck size={17}/></div><div><strong>Paper mode only</strong><span>No live orders are sent</span></div><CheckCircle2 size={15} className="safe-check"/></div><button className="nav-item muted-nav" onClick={() => setTab("Settings")}><Settings2 size={18}/><span>Settings & risk</span></button><div className="profile-row"><div className="profile-avatar">A</div><div className="profile-copy"><strong>Trading workspace</strong><span>Personal account</span></div><CircleHelp size={17}/></div></div>
    </aside>
    <nav className="bottom-nav" aria-label="Main">{navItems.map(item => <button key={item.label} className={`bottom-nav-item ${tab === item.label ? "active" : ""}`} aria-current={tab === item.label ? "page" : undefined} onClick={() => { setTab(item.label); window.scrollTo({ top: 0 }); }}><item.icon size={20}/><span>{item.short}</span></button>)}</nav>
    {mobileNav && <button className="mobile-scrim" onClick={() => setMobileNav(false)} aria-label="Close menu"/>}
    <main className="main-panel">
      <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20}/></button><div className="breadcrumb"><span className="breadcrumb-parent">Workspace</span><span>/</span><strong>{tab}</strong></div></div><div className="topbar-actions"><div className="market-pill" aria-label={streamConnected ? "Live event stream connected" : "Live event stream disconnected"}><span className={streamConnected ? "status-dot" : "status-dot status-offline"}/><span>{streamConnected ? "Live" : "Connecting"}</span></div><button className="icon-button" title="Notifications"><Bell size={18}/><i/></button><div className="top-avatar">A</div></div></header>
      <div className="content-wrap">
        <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot"/> STRATEGY WORKSPACE <span className="eyebrow-sep">/</span> NSE ORB</div><h1>{tab === "Overview" ? "Good trading starts with clarity." : tab}</h1><p>{tab === "Overview" ? "A clear view of your paper strategy, execution quality and AI decisions." : tab === "AI vs no-AI" ? "Measure whether AI decisions improve the same breakout strategy." : tab === "Trade journal" ? "Every simulated entry, exit and decision in one place." : tab === "Backtests" ? "Historical strategy research, kept separate from live paper results."  : tab === "Settings" ? "Configure paper strategy, AI reviews and hard risk controls." : "Keep exposure, losses and execution risk in view."}</p></div><div className="heading-actions"><button className="button-secondary" onClick={() => void refresh(activeRange)} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/>{loading ? "Refreshing" : "Refresh data"}</button><button className="button-primary" onClick={() => { const rows = [["id","timestamp","symbol","side","qty","entry","exit","pnl","reason","ai_decision"], ...filteredTrades.map(t => [t.id,t.ts,t.symbol,t.side,t.qty,t.entry,t.exit ?? "",t.pnl ?? "",t.reason ?? "",t.llm_decision ?? ""])]; const csv = rows.map(row => row.map(v => `"${String(v).replaceAll('"','""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"})); link.download = "orb-paper-trades.csv"; link.click(); URL.revokeObjectURL(link.href); }}><Download size={15}/> Export CSV</button></div></section>
        {tab === "Settings" ? <SettingsPage/> : loading ? (
          <div className="dashboard-loader" role="status" aria-live="polite">
            <RefreshCw size={22} className="spin" />
            <strong>Loading {activeRange} data</strong>
            <span>Fetching the latest paper-trading records…</span>
          </div>
        ) : error ? (
          <div className="notice error-notice">
            <Database size={16} />
            <span><strong>Could not load dashboard data.</strong> {error}</span>
            <button className="text-button" onClick={() => void refresh(activeRange)}>Retry</button>
          </div>
        ) : (
          <>
            {tab !== "Under-₹25 research" && data.trades.length === 0 && openTrades.length === 0 && (
              <div className="notice error-notice">
                <ShieldCheck size={16} />
                <span><strong>No paper trades found for {activeRange}.</strong> Try another range or refresh the data.</span>
              </div>
            )}
            {tab === "Overview" && <Overview trades={closedTrades} totalPnl={totalPnl} unrealizedPnl={unrealizedPnl} matchedAiPnl={matchedAiPnl} winRate={winRate} openCount={openTrades.length} aiSkipped={aiSkipped} equity={equity} controls={matchedControls.length} controlPnl={controlPnl} recentTrades={recentTrades} setTab={setTab} activeRange={activeRange} setActiveRange={setActiveRange} openTrades={openTrades} onManualExit={handleManualExit} manualExitStatus={manualExitStatus}/>}
            {tab === "Trade journal" && <Journal trades={filteredTrades} query={query} setQuery={setQuery} sideFilter={sideFilter} setSideFilter={setSideFilter}/>}
            {tab === "AI vs no-AI" && <AIComparison trades={closedTrades} controls={controlTrades} aiSkipped={aiSkipped}/>}
            {tab === "Backtests" && <ResearchPage runs={data.backtests}/>}
            {tab === "Risk monitor" && <RiskPage trades={closedTrades} openTrades={openTrades} totalPnl={totalPnl}/>}
            {tab === "Under-₹25 research" && <Under25ResearchPage/>}
          </>
        )}
        {manualExitTrade && <div className="manual-exit-modal-backdrop" role="presentation">
          <section className="manual-exit-modal" role="dialog" aria-modal="true" aria-labelledby="manual-exit-title">
            <h2 id="manual-exit-title">Authorize paper exit</h2>
            <p>Exit {manualExitTrade.symbol.replace(".NS", "")} · trade #{manualExitTrade.id}</p>
            <label htmlFor="manual-exit-token">Dashboard control token</label>
            <input id="manual-exit-token" type="password" autoComplete="off" value={manualExitToken} onChange={event => setManualExitToken(event.target.value)} placeholder="Enter control token"/>
            <small>The bot will close this paper position only after it receives a fresh market price. No broker order is sent.</small>
            <div className="manual-exit-modal-actions">
              <button className="button-secondary" onClick={() => { setManualExitTrade(null); setManualExitToken(""); }}>Cancel</button>
              <button className="manual-exit-button" onClick={() => void submitManualExit()} disabled={!manualExitToken.trim() || manualExitStatus[String(manualExitTrade.id)]?.startsWith("Submitting")}>Confirm exit request</button>
            </div>
          </section>
        </div>}
        <footer className="footer"><span><ShieldCheck size={14}/> Paper trading only · No broker orders</span><span>ORB Terminal <b>v0.1</b> <span className="footer-sep">·</span> Data source: Live API</span></footer>
      </div>
    </main>
  </div>;
}

function MetricCard({ label, value, change, positive, icon: Icon, sub }: { label:string; value:string; change?:string; positive?:boolean; icon:typeof Wallet; sub:string }) {
  return <div className="metric-card"><div className="metric-top"><span>{label}</span><div className="metric-icon"><Icon size={17}/></div></div><div className="metric-value">{value}</div><div className="metric-bottom">{change && <span className={positive ? "change positive" : "change negative"}>{positive ? <ArrowUpRight size={13}/> : <ArrowDownRight size={13}/>} {change}</span>}<span className="metric-sub">{sub}</span></div></div>;
}

function Overview({ trades, totalPnl, unrealizedPnl, matchedAiPnl, winRate, openCount, aiSkipped, equity, controls, controlPnl, recentTrades, setTab, activeRange, setActiveRange, openTrades, onManualExit, manualExitStatus }: { trades:PaperTrade[]; totalPnl:number; unrealizedPnl:number; matchedAiPnl:number; winRate:number; openCount:number; aiSkipped:number; equity:{day:string;pnl:number}[]; controls:number; controlPnl:number; recentTrades:PaperTrade[]; setTab:(t:Tab)=>void; activeRange:DashboardRange; setActiveRange:(v:DashboardRange)=>void; openTrades:PaperTrade[]; onManualExit:(trade:PaperTrade)=>void; manualExitStatus:Record<string,string> }) {
  const combinedPnl = totalPnl + unrealizedPnl;
  return <>
    <div className="section-row"><div><h2>Performance overview</h2><p>Realized results for selected period · current open-position marks shown separately</p></div><div className="range-switch">{(["1D","7D","30D","ALL"] as const).map(x=><button key={x} onClick={()=>setActiveRange(x)} className={activeRange===x?"selected":""}>{x}</button>)}</div></div>
    <section className="pnl-summary-panel">
      <div className="pnl-summary-copy"><span className="pnl-summary-label">TOTAL P&amp;L SNAPSHOT</span><strong className={combinedPnl>=0?"positive-text":"negative-text"}>{preciseMoney(combinedPnl)}</strong><small>Selected-period realized P&amp;L + current unrealized P&amp;L across open positions</small></div>
      <div className="pnl-summary-breakdown"><div><span>Realized · {activeRange}</span><strong className={totalPnl>=0?"positive-text":"negative-text"}>{preciseMoney(totalPnl)}</strong></div><div><span>Unrealized · open positions</span><strong className={unrealizedPnl>=0?"positive-text":"negative-text"}>{preciseMoney(unrealizedPnl)}</strong></div></div>
    </section>
    <div className="metric-grid">
      <MetricCard label="Realized P&amp;L" value={money(totalPnl)} change={totalPnl >= 0 ? "Positive" : "Negative"} positive={totalPnl >= 0} icon={Wallet} sub="Confirmed closed trades only"/>
      <MetricCard label="Unrealized P&amp;L" value={money(unrealizedPnl)} positive={unrealizedPnl>=0} icon={Activity} sub="Current open positions · mark-to-market"/>
      <MetricCard label="Win rate" value={trades.length ? `${winRate.toFixed(1)}%` : "—"} icon={TrendingUp} sub={`${trades.filter(t=>Number(t.pnl)>0).length} winning confirmed trades`}/>
      <MetricCard label="Closed trades" value={String(trades.length)} icon={BarChart3} sub={`${openCount} open positions currently`}/>
    </div>
    <div className="main-grid">
      <section className="panel equity-panel"><div className="panel-heading"><div><h3>Equity progression</h3><p>Cumulative realized P&amp;L · INR · {activeRange}</p></div><button className="select-chip">Cumulative <ChevronDown size={14}/></button></div><div className="chart-summary"><strong className={totalPnl >= 0 ? "positive-text":"negative-text"}>{preciseMoney(totalPnl)}</strong><span>Realized in selected period</span><span className="chart-legend"><i/> Cumulative P&amp;L</span></div><div className="equity-chart">{equity.length > 1 ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={equity} margin={{top:10,right:8,left:0,bottom:0}}><defs><linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#9ae6b4" stopOpacity={0.23}/><stop offset="100%" stopColor="#9ae6b4" stopOpacity={0.01}/></linearGradient></defs><CartesianGrid stroke="#242832" strokeDasharray="3 5" vertical={false}/><XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fill:"#777e8e",fontSize:11}}/><YAxis axisLine={false} tickLine={false} tick={{fill:"#777e8e",fontSize:11}} tickFormatter={v=>`₹${v}`} width={54}/><Tooltip contentStyle={{background:"#151821",border:"1px solid #303441",borderRadius:10,color:"#f5f6f8"}} formatter={(v)=>[preciseMoney(Number(v)),"Cumulative P&L"]}/><Area type="monotone" dataKey="pnl" stroke="#9ae6b4" strokeWidth={2.5} fill="url(#pnlFill)" activeDot={{r:4,fill:"#9ae6b4",stroke:"#10130f"}}/></AreaChart></ResponsiveContainer> : <div className="empty-chart"><Activity size={25}/><strong>Not enough history yet</strong><span>More confirmed closed trades will build this chart.</span></div>}</div><div className="chart-foot"><span><i className="tiny-dot green-dot"/> Confirmed realized results only</span><span><Clock3 size={13}/> Updates when data refreshes</span></div></section>
      <section className="panel control-panel"><div className="panel-heading"><div><h3>AI control group</h3><p>AI strategy against no-AI baseline</p></div><div className="control-icon"><Bot size={18}/></div></div><div className="control-callout"><div className="callout-label">NO-AI CONTROL P&amp;L</div><strong className={controlPnl>=0?"positive-text":"negative-text"}>{money(controlPnl)}</strong><span>{controls} completed control trades</span></div><div className="comparison-line"><div><span>AI strategy (matched)</span><strong className={matchedAiPnl>=0?"positive-text":"negative-text"}>{money(matchedAiPnl)}</strong></div><div><span>No-AI control (matched)</span><strong>{money(controlPnl)}</strong></div></div><div className="mini-bar"><span style={{width:`${Math.max(8,Math.min(100,Math.abs(matchedAiPnl)/(Math.abs(matchedAiPnl)+Math.abs(controlPnl)+1)*100))}%`}}/><i style={{width:`${Math.max(8,Math.min(100,Math.abs(controlPnl)/(Math.abs(matchedAiPnl)+Math.abs(controlPnl)+1)*100))}%`}}/></div><button className="panel-link" onClick={()=>setTab("AI vs no-AI")}>Explore AI impact <ArrowUpRight size={15}/></button><div className="research-note"><ShieldCheck size={15}/><span>Control results are hypothetical and do not place orders.</span></div></section>
    </div>
    <section className="panel table-panel open-positions-panel"><div className="panel-heading"><div><h3>Current open positions</h3><p>All active paper positions · current unrealized P&amp;L</p></div><span className="select-chip">{openTrades.length} open</span></div>{openTrades.length ? <TradeTable trades={openTrades} onManualExit={onManualExit} manualExitStatus={manualExitStatus}/> : <div className="table-empty">No open paper positions.</div>}</section>
    <section className="panel table-panel"><div className="panel-heading"><div><h3>Recent trades</h3><p>Your latest simulated executions</p></div><button className="panel-link" onClick={()=>setTab("Trade journal")}>View journal <ArrowUpRight size={15}/></button></div><TradeTable trades={recentTrades}/></section>
    <div className="bottom-grid"><section className="panel insight-panel"><div className="panel-heading"><div><h3>Strategy signals</h3><p>Quick read from your current sample</p></div><Sparkles size={17} className="muted-icon"/></div><div className="insight-row"><div className="insight-symbol"><Bot size={16}/></div><div className="insight-copy"><strong>AI decisions recorded</strong><span>{aiSkipped} skip decisions across visible trades</span></div><span className="insight-value">{trades.length ? `${Math.round(aiSkipped/Math.max(1,trades.length)*100)}%` : "—"}</span></div><div className="insight-row"><div className="insight-symbol"><Activity size={16}/></div><div className="insight-copy"><strong>Control group coverage</strong><span>Completed no-AI outcomes stored</span></div><span className="insight-value">{controls}</span></div></section><section className="panel quick-panel"><div className="panel-heading"><div><h3>Workspace status</h3><p>Data & execution safety</p></div><CheckCircle2 size={17} className="positive-text"/></div><div className="status-row"><span>Execution environment</span><strong><i className="tiny-dot green-dot"/> Paper only</strong></div><div className="status-row"><span>Dashboard data</span><strong>Live API</strong></div><div className="status-row"><span>Broker order routing</span><strong>Disabled</strong></div></section></div>
  </>;
}
function getTradePnl(t: PaperTrade): { value: number | null; kind: "realized" | "unrealized" | "estimated" | "unavailable" } {
  if (t.status === "open") {
    if (t.last_price == null) return { value: null, kind: "unavailable" };
    const direction = t.side === "BUY" ? 1 : -1;
    return { value: (Number(t.last_price) - Number(t.entry)) * Number(t.qty) * direction, kind: "unrealized" };
  }
  if (t.pnl == null) return { value: null, kind: "unavailable" };
  if (t.exit_estimated) return { value: Number(t.pnl), kind: "estimated" };
  return { value: Number(t.pnl), kind: "realized" };
}

function TradeTable({ trades, onManualExit, manualExitStatus = {} }: { trades:PaperTrade[]; onManualExit?:(trade:PaperTrade)=>void; manualExitStatus?:Record<string,string> }) {
  if (!trades.length) return <div className="table-empty">No matching trades found.</div>;
  return <><div className="trade-cards">{trades.map(t=>{
    const name=t.symbol.replace(".NS","");
    const tradePnl = getTradePnl(t);
    const pnl = tradePnl.value;
    const open = tradePnl.kind === "unrealized";
    return <article className="trade-card" key={t.id}>
      <div className="trade-card-top">
        <span className="symbol-icon">{name.slice(0,2)}</span>
        <div className="trade-card-id"><strong>{name}</strong><small>#{t.id} · {formatDate(t.ts)}</small></div>
        <span className={`side-tag ${t.side==="BUY"?"buy":"sell"}`}>{t.side}</span>
        <strong className={`trade-card-pnl ${pnl==null?"":pnl>=0?"positive-text":"negative-text"}`}>{pnl==null?"—":preciseMoney(pnl)}</strong>
      </div>
      <div className="trade-card-mid"><span className="price-pair">{t.entry.toFixed(2)} <span>→</span> {t.exit==null?"Open":Number(t.exit).toFixed(2)}</span>
        <span className="reason-text">{(t.reason ?? (t.status==="open"?"Open position":"—")).split(" (")[0].replaceAll("_"," ")}</span></div>
      <div className="trade-card-tags">
        <span className={`ai-tag ${t.llm_decision==="take"?"ai-take":t.llm_decision==="skip"?"ai-skip":"ai-na"}`}>AI: {t.llm_decision ?? "—"}</span>
        {t.exit_estimated && <span className="est-tag" title="Exit price was reconstructed, not observed. Excluded from confirmed P&L.">estimated exit</span>}
        {open && <span className="mark-tag">unrealised · last {Number(t.last_price).toFixed(2)}</span>}
        {open && onManualExit && <button className="manual-exit-button" onClick={() => onManualExit(t)} disabled={manualExitStatus[String(t.id)]?.startsWith("Submitting") || manualExitStatus[String(t.id)]?.startsWith("Exit queued")}><X size={13}/> {manualExitStatus[String(t.id)]?.startsWith("Exit queued") ? "Exit queued" : "Exit trade"}</button>}
        {manualExitStatus[String(t.id)] && <span className="manual-exit-status">{manualExitStatus[String(t.id)]}</span>}{tradePnl.kind === "estimated" && <span className="est-tag">estimated · excluded from realised P&L</span>}
      </div>
    </article>;
  })}</div><div className="table-scroll"><table><thead><tr><th>Trade / symbol</th><th>Side</th><th>Entry → exit</th><th>Exit reason</th><th>AI decision</th><th>Net P&L</th><th>Timestamp</th><th>Action</th></tr></thead><tbody>{trades.map(t=>{ const tradePnl = getTradePnl(t); const pnl = tradePnl.value; return <tr key={t.id}><td><div className="symbol-cell"><span className="symbol-icon">{t.symbol.replace(".NS","").slice(0,2)}</span><div><strong>{t.symbol.replace(".NS","")}</strong><small>#{t.id}</small></div></div></td><td><span className={`side-tag ${t.side==="BUY"?"buy":"sell"}`}>{t.side}</span></td><td><span className="price-pair">{t.entry.toFixed(2)} <span>→</span> {t.exit == null ? "Open" : Number(t.exit).toFixed(2)}</span></td><td><span className="reason-text">{(t.reason ?? (t.status==="open"?"Open position":"—")).replaceAll("_"," ")}</span></td><td><span className={`ai-tag ${t.llm_decision==="take"?"ai-take":t.llm_decision==="skip"?"ai-skip":"ai-na"}`}>{t.llm_decision ?? "—"}</span></td><td className={pnl==null?"":pnl>=0?"positive-text":"negative-text"}>{pnl == null ? "—" : <>{preciseMoney(pnl)}{tradePnl.kind==="unrealized" && <small className="pnl-kind">Unrealized</small>}{tradePnl.kind==="estimated" && <small className="pnl-kind">Estimated · excluded</small>}</>}</td><td className="date-cell">{formatDate(t.ts)}</td><td>{tradePnl.kind === "unrealized" && onManualExit && <button className="manual-exit-button" onClick={() => onManualExit(t)} disabled={manualExitStatus[String(t.id)]?.startsWith("Submitting") || manualExitStatus[String(t.id)]?.startsWith("Exit queued")}>{manualExitStatus[String(t.id)]?.startsWith("Exit queued") ? "Exit queued" : "Exit trade"}</button>}{manualExitStatus[String(t.id)] && <small className="manual-exit-status">{manualExitStatus[String(t.id)]}</small>}</td></tr>; })}</tbody></table></div></>;
}

function Journal({ trades, query, setQuery, sideFilter, setSideFilter }: { trades:PaperTrade[]; query:string; setQuery:(v:string)=>void; sideFilter:string; setSideFilter:(v:string)=>void }) {
  return <section className="panel journal-panel"><div className="journal-toolbar"><div className="search-box"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search symbol, reason or AI decision"/></div><select value={sideFilter} onChange={e=>setSideFilter(e.target.value)} aria-label="Filter side"><option>All sides</option><option>BUY</option><option>SELL</option></select><button className="button-secondary" onClick={()=>{setQuery("");setSideFilter("All sides");}}><X size={15}/> Reset</button></div><div className="panel-heading journal-heading"><div><h3>Trade journal</h3><p>{trades.length} trades match the current filters</p></div><span className="select-chip"><CalendarDays size={14}/> All available dates</span></div><TradeTable trades={trades}/></section>;
}

function AIComparison({ trades, controls, aiSkipped }: { trades:PaperTrade[]; controls:ControlTrade[]; aiSkipped:number }) {
  const byId = new Map(trades.map(t => [String(t.id), t]));
  const matched = controls.filter(c => {
    if (c.trade_id == null || c.pnl == null) return false;
    const t = byId.get(String(c.trade_id));
    return Boolean(t && t.pnl != null && !t.exit_estimated);
  });
  const pairedTrades = matched.map(c => byId.get(String(c.trade_id))!).filter(Boolean);
  const aiPnl = pairedTrades.reduce((sum,t)=>sum+Number(t.pnl??0),0);
  const controlPnl = matched.reduce((sum,c)=>sum+Number(c.pnl??0),0);
  const aiWinRate = pairedTrades.length ? pairedTrades.filter(t=>Number(t.pnl)>0).length/pairedTrades.length*100 : 0;
  const controlWinRate = matched.length ? matched.filter(t=>Number(t.pnl)>0).length/matched.length*100 : 0;
  const delta = aiPnl-controlPnl;
  const unpaired = controls.filter(c => c.trade_id == null || !byId.has(String(c.trade_id)));
  return <>
    <div className="notice research-notice"><ShieldCheck size={16}/><span><strong>Matched-signal comparison only.</strong> P&amp;L totals below include only completed control outcomes linked to a confirmed, non-estimated AI-managed paper trade. AI-skipped signals have no executed AI trade and are shown separately, not mixed into the P&amp;L difference.</span></div>
    <div className="metric-grid compare-metrics">
      <MetricCard label="AI P&amp;L (matched)" value={money(aiPnl)} icon={Bot} sub={`${pairedTrades.length} matched AI trades`}/>
      <MetricCard label="No-AI P&amp;L (matched)" value={money(controlPnl)} icon={Activity} sub={`${matched.length} matched control outcomes`}/>
      <MetricCard label="Matched P&amp;L difference" value={money(delta)} positive={delta>=0} icon={TrendingUp} sub="AI minus no-AI, same linked trades"/>
      <MetricCard label="AI skip decisions" value={String(aiSkipped)} icon={ShieldCheck} sub={`${unpaired.length} unpaired controls (mostly skipped signals)`}/>
    </div>
    <div className="main-grid">
      <section className="panel"><div className="panel-heading"><div><h3>Matched strategy comparison</h3><p>Completed, linked signal outcomes · INR</p></div></div>
        {matched.length ? <div className="compare-rows"><CompareBar label="AI strategy" value={aiPnl} max={Math.max(Math.abs(aiPnl),Math.abs(controlPnl),1)}/><CompareBar label="No-AI control" value={controlPnl} max={Math.max(Math.abs(aiPnl),Math.abs(controlPnl),1)}/></div> : <div className="empty-inline"><CircleHelp size={18}/><span>No matched completed control outcomes yet. The dashboard will not infer a comparison from unrelated trades.</span></div>}
        <div className="research-note"><CircleHelp size={15}/><span>Only linked trade IDs are comparable here. Unlinked controls are not counted in this P&amp;L delta.</span></div>
      </section>
      <section className="panel"><div className="panel-heading"><div><h3>Matched quality indicators</h3><p>Paired sample only</p></div></div>
        <div className="status-row"><span>AI win rate (matched)</span><strong>{aiWinRate.toFixed(1)}%</strong></div>
        <div className="status-row"><span>No-AI win rate (matched)</span><strong>{controlWinRate.toFixed(1)}%</strong></div>
        <div className="status-row"><span>Matched sample size</span><strong>{matched.length}</strong></div>
        <div className="status-row"><span>Unpaired control outcomes</span><strong>{unpaired.length}</strong></div>
      </section>
    </div>
    <section className="panel table-panel"><div className="panel-heading"><div><h3>Matched control-group outcomes</h3><p>Rows with a linked, confirmed AI paper trade only</p></div><span className="ai-tag ai-na">MATCHED ONLY</span></div>
      {matched.length ? <div className="table-scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>AI decision</th><th>Exit reason</th><th>Entry → exit</th><th>AI P&amp;L</th><th>No-AI P&amp;L</th><th>Closed at</th></tr></thead><tbody>{matched.map(c=>{const t=byId.get(String(c.trade_id))!;return <tr key={c.id}><td><strong>{c.symbol.replace(".NS","")}</strong></td><td><span className={`side-tag ${c.side==="BUY"?"buy":"sell"}`}>{c.side??"—"}</span></td><td><span className={`ai-tag ${t.llm_decision==="take"?"ai-take":t.llm_decision==="skip"?"ai-skip":"ai-na"}`}>{t.llm_decision??"—"}</span></td><td>{(c.exit_reason??"—").replaceAll("_"," ")}</td><td>{c.entry_price?.toFixed(2)??"—"} → {c.exit_price?.toFixed(2)??"—"}</td><td className={Number(t.pnl)>=0?"positive-text":"negative-text"}>{preciseMoney(Number(t.pnl))}</td><td className={Number(c.pnl)>=0?"positive-text":"negative-text"}>{preciseMoney(Number(c.pnl))}</td><td className="date-cell">{formatDate(c.ts)}</td></tr>})}</tbody></table></div> : <div className="table-empty">No linked matched outcomes are available yet.</div>}
    </section>
    <section className="panel table-panel"><div className="panel-heading"><div><h3>Unpaired no-AI outcomes</h3><p>Kept separate because no corresponding executed AI trade is linked</p></div><span className="ai-tag ai-na">NOT IN P&amp;L DELTA</span></div>
      {unpaired.length ? <div className="table-scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>AI decision</th><th>Outcome</th><th>Hypothetical P&amp;L</th><th>Closed at</th></tr></thead><tbody>{unpaired.map(c=><tr key={c.id}><td><strong>{c.symbol.replace(".NS","")}</strong></td><td>{c.side??"—"}</td><td>{c.ai_decision??"—"}</td><td>{(c.exit_reason??"—").replaceAll("_"," ")}</td><td className={Number(c.pnl)>=0?"positive-text":"negative-text"}>{c.pnl==null?"—":preciseMoney(Number(c.pnl))}</td><td className="date-cell">{formatDate(c.ts)}</td></tr>)}</tbody></table></div> : <div className="table-empty">No unpaired control outcomes in this date range.</div>}
    </section>
  </>;
}
function CompareBar({label,value,max}:{label:string;value:number;max:number}) { return <div className="compare-bar-row"><div><span>{label}</span><strong className={value>=0?"positive-text":"negative-text"}>{money(value)}</strong></div><div className="compare-track"><span className={value>=0?"bar-positive":"bar-negative"} style={{width:`${Math.max(3,Math.abs(value)/max*100)}%`}}/></div></div>; }

function ResearchPage({runs}:{runs:BacktestRun[]}) {
  const latest = runs[0];
  const baseline = latest?.result?.baseline;
  const test = latest?.result?.test;
  const totalRuns = runs.length;
  return <>
    <div className="metric-grid">
      <MetricCard label="Saved backtest runs" value={String(totalRuns)} icon={BarChart3} sub="Loaded from Supabase backtest_runs"/>
      <MetricCard label="Latest baseline P&amp;L" value={baseline?.total == null ? "—" : money(Number(baseline.total))} icon={TrendingUp} sub={baseline?.n == null ? "No baseline summary" : `${baseline.n} trades in latest run`}/>
      <MetricCard label="Out-of-sample P&amp;L" value={test?.total == null ? "—" : money(Number(test.total))} icon={Activity} sub={test?.n == null ? "No test split recorded" : `${test.n} test trades`}/>
      <MetricCard label="Latest verdict" value={baseline?.verdict ? (String(baseline.verdict).startsWith("REJECT") ? "Reject" : "Review") : "—"} icon={ShieldCheck} sub="Read from saved result, not inferred"/>
    </div>
    {latest ? <section className="panel backtest-detail"><div className="panel-heading"><div><h3>Latest backtest</h3><p>Saved {formatDate(latest.created_at)} · run #{latest.id}</p></div><span className="ai-tag ai-na">HISTORICAL RESEARCH</span></div>
      {latest.summary_md ? <pre className="backtest-summary">{latest.summary_md}</pre> : <div className="empty-inline"><CircleHelp size={18}/><span>This run has structured results but no summary text.</span></div>}
    </section> : <section className="panel empty-research"><div className="empty-research-icon"><BarChart3 size={23}/></div><h3>No saved backtests are available</h3><p>Once read access to backtest_runs is configured, saved historical runs will appear here. Backtests stay separate from live paper performance.</p><span className="ai-tag ai-na">NO BACKTEST DATA LOADED</span></section>}
    {runs.length > 1 && <section className="panel table-panel"><div className="panel-heading"><div><h3>Backtest history</h3><p>Saved runs newest first</p></div></div><div className="table-scroll"><table><thead><tr><th>Run</th><th>Created</th><th>Baseline trades</th><th>Baseline P&amp;L</th><th>Expectancy</th><th>Profit factor</th><th>Test P&amp;L</th></tr></thead><tbody>{runs.map(run=>{const b=run.result?.baseline;const t=run.result?.test;return <tr key={run.id}><td>#{run.id}</td><td className="date-cell">{formatDate(run.created_at)}</td><td>{b?.n??"—"}</td><td>{b?.total==null?"—":money(Number(b.total))}</td><td>{b?.exp==null?"—":preciseMoney(Number(b.exp))}</td><td>{b?.pf==null?"—":Number(b.pf).toFixed(2)}</td><td>{t?.total==null?"—":money(Number(t.total))}</td></tr>})}</tbody></table></div></section>}
  </>;
}

type NumericSettingKey = Exclude<keyof BotSettings, "square_off_time" | "emergency_stop" | "paper_only">;

function Under25ResearchPage() {
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");
  const [loadingReport, setLoadingReport] = useState(true);
  const load = useCallback(async () => {
    setLoadingReport(true); setError("");
    try {
      const response = await fetch("/api/research/under-25", { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Unable to load the research report.");
      setReport(payload);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load the research report."); }
    finally { setLoadingReport(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  if (loadingReport) return <section className="panel"><p>Loading under-₹25 research report…</p></section>;
  if (error) return <section className="panel"><div className="notice error-notice"><Database size={16}/><span>{error}</span><button className="text-button" onClick={() => void load()}>Retry</button></div><p>Run the separate research scanner during NSE market hours to generate the first report.</p></section>;
  const coverage = report?.coverage ?? {};
  const candidates = Array.isArray(report?.candidates) ? report.candidates : [];
  return <>
    <div className="notice"><ShieldCheck size={16}/><span><strong>Research only · Paper only.</strong> This scanner cannot place orders and does not replace the Nifty 50 strategy.</span><button className="text-button" onClick={() => void load()}>Refresh</button></div>
    <div className="metric-grid">
      <MetricCard label="Scan status" value={String(report.status ?? "unknown").toUpperCase()} icon={Activity} sub={report.generated_at ? formatDate(report.generated_at) : "No timestamp"}/>
      <MetricCard label="Fresh quotes" value={`${coverage.fresh_quotes ?? 0} / ${coverage.instruments ?? 0}`} icon={TrendingUp} sub="Full-universe quote coverage"/>
      <MetricCard label="Liquidity validated" value={String(coverage.liquidity_values ?? 0)} icon={Database} sub={`${coverage.price_candidates_requiring_history ?? 0} price-qualified`}/>
      <MetricCard label="Eligible candidates" value={String(candidates.length)} icon={CheckCircle2} sub="Ranked by average turnover"/>
    </div>
    <section className="panel">
      <div className="panel-heading"><div><h3>Screening criteria</h3><p>Applied to fresh Angel One quotes and completed daily candles.</p></div><span className="ai-tag ai-na">{report.status ?? "unknown"}</span></div>
      <div className="status-row"><span>Maximum price</span><strong>₹{report.criteria?.max_price_inr ?? "25.00"}</strong></div>
      <div className="status-row"><span>Minimum average daily value</span><strong>{money(Number(report.criteria?.min_avg_daily_traded_value_inr ?? 50000000))}</strong></div>
      <div className="status-row"><span>Maximum spread</span><strong>{report.criteria?.max_spread_pct ?? "0.50"}%</strong></div>
      <div className="status-row"><span>Quote freshness</span><strong>{report.criteria?.max_quote_age_seconds ?? 45}s</strong></div>
      {Object.keys(report.history_errors ?? {}).length > 0 && <div className="notice error-notice"><span><strong>History errors:</strong> {Object.keys(report.history_errors).length} symbols. Partial coverage is not a complete scan.</span></div>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><h3>Eligible stocks</h3><p>Price, spread and 20-session liquidity filters passed.</p></div></div>
      {candidates.length ? <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Price</th><th>Bid / Ask</th><th>Spread</th><th>Avg daily value</th><th>Quote age</th></tr></thead><tbody>{candidates.map((row:any) => <tr key={row.symbol}><td><strong>{row.symbol}</strong></td><td>{preciseMoney(Number(row.price))}</td><td>{preciseMoney(Number(row.bid))} / {preciseMoney(Number(row.ask))}</td><td>{Number(row.spread_pct).toFixed(3)}%</td><td>{money(Number(row.avg_daily_traded_value))}</td><td>{Number(row.quote_age_seconds).toFixed(1)}s</td></tr>)}</tbody></table></div> : <div className="empty-inline"><Activity size={18}/><span>No eligible stocks in the latest report.</span></div>}
    </section>
  </>;
}

function SettingsPage() {
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void loadBotSettings().then(data => { if (active) setSettings(data.settings); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : "Unable to load settings."); });
    return () => { active = false; };
  }, []);
  const setNumber = (key: NumericSettingKey, value: string) => {
    if (!settings) return;
    setSettings({ ...settings, [key]: Number(value) });
  };
  const save = async () => {
    if (!settings || !token.trim()) { setError("Enter the dashboard control token to save settings."); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await saveBotSettings({
        scan_interval_seconds: settings.scan_interval_seconds,
        position_review_seconds: settings.position_review_seconds,
        risk_per_trade_pct: settings.risk_per_trade_pct,
        daily_loss_cap_pct: settings.daily_loss_cap_pct,
        max_open_positions: settings.max_open_positions,
        max_trades_per_day: settings.max_trades_per_day,
        breakeven_r: settings.breakeven_r,
        profit_protection_r: settings.profit_protection_r,
        protected_profit_r: settings.protected_profit_r,
        trailing_start_r: settings.trailing_start_r,
        square_off_time: settings.square_off_time,
        stale_quote_seconds: settings.stale_quote_seconds,
        ai_position_min_confidence: settings.ai_position_min_confidence,
        emergency_stop: settings.emergency_stop,
        sentiment_enabled: settings.sentiment_enabled,
        ai_position_management_enabled: settings.ai_position_management_enabled,
      }, token.trim());
      setSettings(result.settings); setToken("");
      setMessage(`Saved settings version ${result.version}. Bot applies changes within approximately 15 seconds.`);
    } catch (e) { setToken(""); setError(e instanceof Error ? e.message : "Settings save failed."); }
    finally { setBusy(false); }
  };
  if (!settings && !error) return <section className="panel"><p>Loading strategy settings…</p></section>;
  if (!settings) return <section className="panel"><div className="notice error-notice">{error}</div></section>;
  const numeric = (label: string, key: NumericSettingKey, min: number, max: number, step: number, suffix = "") =>
    <label className="setting-field" key={String(key)}><span>{label}</span><div><input type="number" min={min} max={max} step={step} value={Number(settings[key])} onChange={e => setNumber(key, e.target.value)}/><small>{min}–{max}{suffix}</small></div></label>;
  return <>
    <section className="panel settings-panel">
      <div className="panel-heading"><div><h3>Entry & AI schedule</h3><p>Changes are versioned and read by the paper runner.</p></div><span className="ai-tag ai-na">LIVE CONFIG</span></div>
      <div className="settings-grid">
        {numeric("Nifty 50 scan interval", "scan_interval_seconds", 60, 900, 30, " sec")}
        {numeric("Open-position AI review", "position_review_seconds", 60, 1800, 60, " sec")}
        {numeric("AI position confidence minimum", "ai_position_min_confidence", 0, 1, 0.05)}
        {numeric("Stale quote rejection", "stale_quote_seconds", 10, 90, 5, " sec")}
      </div>
    </section>
    <section className="panel settings-panel">
      <div className="panel-heading"><div><h3>Risk limits</h3><p>Hard limits enforced again by the deterministic risk engine.</p></div><ShieldCheck size={18}/></div>
      <div className="settings-grid">
        {numeric("Risk per trade", "risk_per_trade_pct", 0.1, 1, 0.1, "%")}
        {numeric("Daily loss cap", "daily_loss_cap_pct", 0.5, 2, 0.1, "%")}
        {numeric("Maximum open positions", "max_open_positions", 1, 2, 1)}
        {numeric("Maximum trades per day", "max_trades_per_day", 1, 3, 1)}
      </div>
    </section>
    <section className="panel settings-panel">
      <div className="panel-heading"><div><h3>Position protection & schedule</h3><p>Profit protection thresholds are measured in initial risk units (R).</p></div></div>
      <div className="settings-grid">
        {numeric("Move toward breakeven", "breakeven_r", 0.5, 2, 0.1, " R")}
        {numeric("Profit protection starts", "profit_protection_r", 1, 3, 0.1, " R")}
        {numeric("Net profit to protect", "protected_profit_r", 0.1, 1.5, 0.1, " R")}
        {numeric("ATR / swing trailing starts", "trailing_start_r", 1.5, 4, 0.1, " R")}
        <label className="setting-field"><span>Forced square-off (IST)</span><div><input type="time" min="15:00" max="15:25" value={settings.square_off_time} onChange={e => setSettings({...settings, square_off_time:e.target.value})}/><small>15:00–15:25</small></div></label>
      </div>
    </section>
    <section className="panel settings-panel">
      <div className="panel-heading"><div><h3>AI & data features</h3><p>Optional context and position review controls.</p></div><Bot size={18}/></div>
      <label className="feature-toggle"><span><strong>AI position management</strong><small>Batch review open positions and apply validated HOLD/SL/target/EXIT actions.</small></span><input type="checkbox" checked={settings.ai_position_management_enabled} onChange={e => setSettings({...settings, ai_position_management_enabled:e.target.checked})}/></label>
      <label className="feature-toggle"><span><strong>News sentiment context</strong><small>Use available Google News RSS sentiment as context only; it never creates or vetoes a breakout.</small></span><input type="checkbox" checked={settings.sentiment_enabled} onChange={e => setSettings({...settings, sentiment_enabled:e.target.checked})}/></label>
    </section>
    <section className="panel settings-panel emergency-settings">
      <div><h3>Emergency stop</h3><p>When enabled, the bot halts new entries and attempts to close every open paper position using fresh Angel One quotes. It never sends broker orders.</p></div>
      <label className="emergency-toggle"><input type="checkbox" checked={settings.emergency_stop} onChange={e => { if (e.target.checked && !window.confirm("Emergency stop will halt new entries and attempt to close every open paper position at a fresh Angel One quote. Continue?")) return; setSettings({...settings, emergency_stop:e.target.checked}); }}/><span>{settings.emergency_stop ? "STOP ACTIVE" : "Disabled"}</span></label>
    </section>
    <section className="panel settings-panel">
      <div className="settings-readonly"><ShieldCheck size={17}/><div><strong>Paper-only execution is locked</strong><span>Live broker orders cannot be enabled from this dashboard.</span></div><b>ON</b></div>
      <label className="setting-token"><span>Dashboard control token</span><input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} placeholder="Enter token to save settings"/></label>
      {error && <div className="notice error-notice">{error}</div>}
      {message && <div className="notice success-notice">{message}</div>}
      <div className="settings-actions"><button className="button-secondary" onClick={() => {setError("");setMessage("");void loadBotSettings().then(d=>setSettings(d.settings)).catch(e=>setError(e.message));}}>Reload</button><button className="button-primary" onClick={() => void save()} disabled={busy || !token.trim()}>{busy ? "Saving…" : "Save settings"}</button></div>
    </section>
  </>;
}

function RiskPage({trades,openTrades,totalPnl}:{trades:PaperTrade[];openTrades:PaperTrade[];totalPnl:number}) {
  const exposure=openTrades.reduce((s,t)=>s+Number(t.qty)*Number(t.last_price??t.entry),0);
  const losses=trades.filter(t=>Number(t.pnl)<0).length;
  return <><div className="metric-grid"><MetricCard label="Open positions" value={String(openTrades.length)} icon={Activity} sub="Unclosed paper positions"/><MetricCard label="Marked exposure" value={money(exposure)} icon={Wallet} sub="Based on last known marks"/><MetricCard label="Realized P&L" value={money(totalPnl)} positive={totalPnl>=0} icon={TrendingUp} sub="Estimated exits excluded"/><MetricCard label="Losing trades" value={String(losses)} icon={ShieldCheck} sub="Closed trades only"/></div><div className="main-grid"><section className="panel"><div className="panel-heading"><div><h3>Risk guardrails</h3><p>Configured strategy limits</p></div><ShieldCheck size={17} className="positive-text"/></div><div className="status-row"><span>Risk per trade</span><strong>Configured in bot env</strong></div><div className="status-row"><span>Daily loss cap</span><strong>Configured in bot env</strong></div><div className="status-row"><span>Maximum entries per day</span><strong>Configured in bot env</strong></div><div className="status-row"><span>Order environment</span><strong className="positive-text">Paper only</strong></div></section><section className="panel"><div className="panel-heading"><div><h3>Open position marks</h3><p>Latest values reported by the bot</p></div></div>{openTrades.length ? openTrades.map(t=><div className="insight-row" key={t.id}><div className="symbol-icon">{t.symbol.slice(0,2)}</div><div className="insight-copy"><strong>{t.symbol.replace(".NS","")} · {t.side}</strong><span>{t.qty} shares · last mark {t.last_price?.toFixed(2)??"not available"}</span></div><span className="insight-value">{t.last_price_ts?formatDate(t.last_price_ts):"—"}</span></div>):<div className="empty-inline"><CheckCircle2 size={18}/><span>No open positions reported.</span></div>}</section></div></>;
}

export default App;