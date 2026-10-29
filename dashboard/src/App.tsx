import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, BarChart3, Bell, Bot, CalendarDays,
  CheckCircle2, ChevronDown, CircleHelp, Clock3, Database, Download,
  LayoutDashboard, ListFilter, Menu, RefreshCw, Search, Settings2, ShieldCheck,
  SlidersHorizontal, Sparkles, TrendingUp, Wallet, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { isSupabaseConfigured, loadDashboardData } from "./lib/supabase";
import type { ControlTrade, PaperTrade } from "./lib/supabase";

type Tab = "Overview" | "Trade journal" | "AI vs no-AI" | "Backtests" | "Risk monitor";
type DashboardData = { trades: PaperTrade[]; controls: ControlTrade[] };

const demoTrades: PaperTrade[] = [
  { id: 901, ts: "2026-10-29T09:44:00+05:30", symbol: "RELIANCE.NS", side: "BUY", qty: 8, entry: 1468.2, exit: 1481.4, pnl: 94.62, reason: "target", status: "closed", llm_decision: "take", llm_reason: "Breakout holds above opening range." },
  { id: 900, ts: "2026-10-29T09:38:00+05:30", symbol: "TCS.NS", side: "SELL", qty: 3, entry: 3140.5, exit: 3152.8, pnl: -47.2, reason: "stop_loss", status: "closed", llm_decision: "take", llm_reason: "Momentum confirmed below range." },
  { id: 899, ts: "2026-10-28T11:16:00+05:30", symbol: "INFY.NS", side: "BUY", qty: 10, entry: 1538.1, exit: 1551.6, pnl: 119.4, reason: "target", status: "closed", llm_decision: "skip", llm_reason: "Mixed momentum; volume confirmation weak." },
  { id: 898, ts: "2026-10-28T10:02:00+05:30", symbol: "HDFCBANK.NS", side: "SELL", qty: 7, entry: 968.5, exit: 972.2, pnl: -35.8, reason: "stop_loss", status: "closed", llm_decision: "take", llm_reason: "Range breakdown with follow-through." },
  { id: 897, ts: "2026-10-27T12:03:00+05:30", symbol: "ICICIBANK.NS", side: "BUY", qty: 9, entry: 1284.7, exit: 1300.3, pnl: 126.2, reason: "target", status: "closed", llm_decision: "take", llm_reason: "Price structure supports continuation." },
  { id: 896, ts: "2026-10-27T09:53:00+05:30", symbol: "RELIANCE.NS", side: "SELL", qty: 8, entry: 1472.0, exit: 1480.1, pnl: -72.4, reason: "stop_loss", status: "closed", llm_decision: "skip", llm_reason: "Breakout appears stretched." },
];
const demoControls: ControlTrade[] = [
  { id: 21, trade_id: 901, symbol: "RELIANCE.NS", variant: "no_ai_control", side: "BUY", qty: 8, entry_price: 1468.2, exit_price: 1481.4, exit_reason: "target", ai_decision: "take", pnl: 94.62, baseline_pnl: null, ts: "2026-10-29T10:02:00+05:30" },
  { id: 20, trade_id: 900, symbol: "TCS.NS", variant: "no_ai_control", side: "SELL", qty: 3, entry_price: 3140.5, exit_price: 3152.8, exit_reason: "stop_loss", ai_decision: "take", pnl: -47.2, baseline_pnl: null, ts: "2026-10-29T10:15:00+05:30" },
  { id: 19, trade_id: null, symbol: "INFY.NS", variant: "no_ai_control", side: "BUY", qty: 10, entry_price: 1538.1, exit_price: 1551.6, exit_reason: "target", ai_decision: "skip", pnl: 119.4, baseline_pnl: null, ts: "2026-10-28T11:35:00+05:30" },
  { id: 18, trade_id: 898, symbol: "HDFCBANK.NS", variant: "no_ai_control", side: "SELL", qty: 7, entry_price: 968.5, exit_price: 972.2, exit_reason: "stop_loss", ai_decision: "take", pnl: -35.8, baseline_pnl: null, ts: "2026-10-28T10:25:00+05:30" },
  { id: 17, trade_id: null, symbol: "ICICIBANK.NS", variant: "no_ai_control", side: "BUY", qty: 9, entry_price: 1284.7, exit_price: 1300.3, exit_reason: "target", ai_decision: "skip", pnl: 126.2, baseline_pnl: null, ts: "2026-10-27T12:22:00+05:30" },
];
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
const preciseMoney = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);
const formatDate = (value: string) => new Date(value).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

function App() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [data, setData] = useState<DashboardData>({ trades: demoTrades, controls: demoControls });
  const [demo, setDemo] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [sideFilter, setSideFilter] = useState("All sides");
  const [activeRange, setActiveRange] = useState("7D");
  const [mobileNav, setMobileNav] = useState(false);

  const refresh = useCallback(async () => {
    if (!isSupabaseConfigured) { setDemo(true); return; }
    setLoading(true); setError("");
    try {
      const fresh = await loadDashboardData();
      setData(fresh); setDemo(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load dashboard data.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const closedTrades = useMemo(() => {
    const closed = data.trades.filter(t => t.status !== "open" && t.pnl !== null && !t.exit_estimated);
    if (activeRange === "ALL") return closed;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - (activeRange === "1D" ? 1 : activeRange === "30D" ? 30 : 7));
    return closed.filter(t => new Date(t.ts) >= cutoff);
  }, [data.trades, activeRange]);
  const totalPnl = closedTrades.reduce((sum, t) => sum + Number(t.pnl ?? 0), 0);
  const winners = closedTrades.filter(t => Number(t.pnl) > 0).length;
  const winRate = closedTrades.length ? winners / closedTrades.length * 100 : 0;
  const openTrades = data.trades.filter(t => t.status === "open");
  const controlTrades = data.controls.filter(t => t.pnl !== null && (activeRange === "ALL" || new Date(t.ts) >= new Date(Date.now() - (activeRange === "1D" ? 1 : activeRange === "30D" ? 30 : 7) * 86400000)));
  const controlPnl = controlTrades.reduce((sum, t) => sum + Number(t.pnl ?? 0), 0);
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
      const day = new Date(trade.ts).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
      byDay.set(day, total);
    }
    return [...byDay.entries()].map(([day, pnl]) => ({ day, pnl }));
  }, [closedTrades]);

  const navItems: { label: Tab; icon: typeof LayoutDashboard; hint: string }[] = [
    { label: "Overview", icon: LayoutDashboard, hint: "Performance snapshot" },
    { label: "Trade journal", icon: ListFilter, hint: "Entries & exits" },
    { label: "AI vs no-AI", icon: Bot, hint: "Control group" },
    { label: "Backtests", icon: BarChart3, hint: "Strategy research" },
    { label: "Risk monitor", icon: ShieldCheck, hint: "Exposure & limits" },
  ];

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="brand"><div className="brand-mark"><Activity size={20}/></div><div><strong>ORB<span>TERMINAL</span></strong><small>Paper trading workspace</small></div><button className="icon-button mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={18}/></button></div>
      <div className="workspace-label">WORKSPACE</div>
      <div className="workspace-switch"><div className="workspace-avatar">P</div><div className="workspace-copy"><strong>Paper account</strong><span>NSE · Intraday</span></div><ChevronDown size={15}/></div>
      <div className="nav-caption">ANALYTICS</div>
      <nav>{navItems.map(item => <button key={item.label} className={`nav-item ${tab === item.label ? "active" : ""}`} onClick={() => { setTab(item.label); setMobileNav(false); }}><item.icon size={18}/><span>{item.label}</span>{item.label === "AI vs no-AI" && <span className="nav-new">NEW</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="safe-card"><div className="safe-icon"><ShieldCheck size={17}/></div><div><strong>Paper mode only</strong><span>No live orders are sent</span></div><CheckCircle2 size={15} className="safe-check"/></div><button className="nav-item muted-nav" onClick={() => setTab("Risk monitor")}><Settings2 size={18}/><span>Settings & risk</span></button><div className="profile-row"><div className="profile-avatar">A</div><div className="profile-copy"><strong>Trading workspace</strong><span>Personal account</span></div><CircleHelp size={17}/></div></div>
    </aside>
    {mobileNav && <button className="mobile-scrim" onClick={() => setMobileNav(false)} aria-label="Close menu"/>}
    <main className="main-panel">
      <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20}/></button><div className="breadcrumb">Workspace <span>/</span> <strong>{tab}</strong></div></div><div className="topbar-actions"><div className="market-pill"><span className="status-dot"/><span>Paper environment</span></div><button className="icon-button" title="Notifications"><Bell size={18}/><i/></button><div className="top-avatar">A</div></div></header>
      <div className="content-wrap">
        <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot"/> STRATEGY WORKSPACE <span className="eyebrow-sep">/</span> NSE ORB</div><h1>{tab === "Overview" ? "Good trading starts with clarity." : tab}</h1><p>{tab === "Overview" ? "A clear view of your paper strategy, execution quality and AI decisions." : tab === "AI vs no-AI" ? "Measure whether AI decisions improve the same breakout strategy." : tab === "Trade journal" ? "Every simulated entry, exit and decision in one place." : tab === "Backtests" ? "Historical strategy research, kept separate from live paper results." : "Keep exposure, losses and execution risk in view."}</p></div><div className="heading-actions"><button className="button-secondary" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/>{loading ? "Refreshing" : "Refresh data"}</button><button className="button-primary" onClick={() => { const rows = [["id","timestamp","symbol","side","qty","entry","exit","pnl","reason","ai_decision"], ...filteredTrades.map(t => [t.id,t.ts,t.symbol,t.side,t.qty,t.entry,t.exit ?? "",t.pnl ?? "",t.reason ?? "",t.llm_decision ?? ""])]; const csv = rows.map(row => row.map(v => `"${String(v).replaceAll('"','""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"})); link.download = "orb-paper-trades.csv"; link.click(); URL.revokeObjectURL(link.href); }}><Download size={15}/> Export CSV</button></div></section>
        {demo && <div className="notice demo-notice"><Sparkles size={16}/><span><strong>Preview mode.</strong> Sample data is shown. Add your Supabase URL and publishable/anon key to load your real paper-trading records.</span><span className="notice-tag">DEMO DATA</span></div>}
        {error && <div className="notice error-notice"><Database size={16}/><span><strong>Could not refresh data.</strong> {error}</span><button className="text-button" onClick={() => void refresh()}>Retry</button></div>}
        {tab === "Overview" && <Overview trades={closedTrades} totalPnl={totalPnl} winRate={winRate} openCount={openTrades.length} aiSkipped={aiSkipped} equity={equity} controls={controlTrades.length} controlPnl={controlPnl} setTab={setTab}/>}
        {tab === "Trade journal" && <Journal trades={filteredTrades} query={query} setQuery={setQuery} sideFilter={sideFilter} setSideFilter={setSideFilter}/>}
        {tab === "AI vs no-AI" && <AIComparison trades={closedTrades} controls={controlTrades} aiPnl={totalPnl} controlPnl={controlPnl} aiSkipped={aiSkipped}/>}
        {tab === "Backtests" && <ResearchPage/>}
        {tab === "Risk monitor" && <RiskPage trades={closedTrades} openTrades={openTrades} totalPnl={totalPnl}/>}
        <footer className="footer"><span><ShieldCheck size={14}/> Paper trading only · No broker orders</span><span>ORB Terminal <b>v0.1</b> <span className="footer-sep">·</span> Data source: {demo ? "sample preview" : "Supabase"}</span></footer>
      </div>
    </main>
  </div>;
}

function MetricCard({ label, value, change, positive, icon: Icon, sub }: { label:string; value:string; change?:string; positive?:boolean; icon:typeof Wallet; sub:string }) {
  return <div className="metric-card"><div className="metric-top"><span>{label}</span><div className="metric-icon"><Icon size={17}/></div></div><div className="metric-value">{value}</div><div className="metric-bottom">{change && <span className={positive ? "change positive" : "change negative"}>{positive ? <ArrowUpRight size={13}/> : <ArrowDownRight size={13}/>} {change}</span>}<span className="metric-sub">{sub}</span></div></div>;
}

function Overview({ trades, totalPnl, winRate, openCount, aiSkipped, equity, controls, controlPnl, setTab }: { trades:PaperTrade[]; totalPnl:number; winRate:number; openCount:number; aiSkipped:number; equity:{day:string;pnl:number}[]; controls:number; controlPnl:number; setTab:(t:Tab)=>void }) {
  const recent = [...trades].sort((a,b) => new Date(b.ts).getTime()-new Date(a.ts).getTime()).slice(0,5);
  return <>
    <div className="section-row"><div><h2>Performance overview</h2><p>Closed paper trades · estimated exits excluded</p></div><div className="range-switch">{["1D","7D","30D","ALL"].map(x=><button key={x} onClick={()=>setActiveRange(x)} className={activeRange===x?"selected":""}>{x}</button>)}</div></div>
    <div className="metric-grid">
      <MetricCard label="Net realized P&L" value={money(totalPnl)} change={totalPnl >= 0 ? "Positive" : "Negative"} positive={totalPnl >= 0} icon={Wallet} sub="After recorded trading costs"/>
      <MetricCard label="Win rate" value={`${winRate.toFixed(1)}%`} icon={TrendingUp} sub={`${trades.filter(t=>Number(t.pnl)>0).length} winning trades`}/>
      <MetricCard label="Closed trades" value={String(trades.length)} icon={BarChart3} sub={`${openCount} currently open`}/>
      <MetricCard label="AI skip decisions" value={String(aiSkipped)} icon={Bot} sub="Recorded on paper trades"/>
    </div>
    <div className="main-grid">
      <section className="panel equity-panel"><div className="panel-heading"><div><h3>Equity progression</h3><p>Cumulative realized P&L · INR</p></div><button className="select-chip">Cumulative <ChevronDown size={14}/></button></div><div className="chart-summary"><strong className={totalPnl >= 0 ? "positive-text":"negative-text"}>{preciseMoney(totalPnl)}</strong><span>Net realized</span><span className="chart-legend"><i/> Cumulative P&L</span></div><div className="equity-chart">{equity.length > 1 ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={equity} margin={{top:10,right:8,left:0,bottom:0}}><defs><linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#9ae6b4" stopOpacity={0.23}/><stop offset="100%" stopColor="#9ae6b4" stopOpacity={0.01}/></linearGradient></defs><CartesianGrid stroke="#242832" strokeDasharray="3 5" vertical={false}/><XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fill:"#777e8e",fontSize:11}}/><YAxis axisLine={false} tickLine={false} tick={{fill:"#777e8e",fontSize:11}} tickFormatter={v=>`₹${v}`} width={54}/><Tooltip contentStyle={{background:"#151821",border:"1px solid #303441",borderRadius:10,color:"#f5f6f8"}} formatter={(v)=>[preciseMoney(Number(v)),"Cumulative P&L"]}/><Area type="monotone" dataKey="pnl" stroke="#9ae6b4" strokeWidth={2.5} fill="url(#pnlFill)" activeDot={{r:4,fill:"#9ae6b4",stroke:"#10130f"}}/></AreaChart></ResponsiveContainer> : <div className="empty-chart"><Activity size={25}/><strong>Not enough history yet</strong><span>More closed trading sessions will build this chart.</span></div>}</div><div className="chart-foot"><span><i className="tiny-dot green-dot"/> Realized results only</span><span><Clock3 size={13}/> Updates when data refreshes</span></div></section>
      <section className="panel control-panel"><div className="panel-heading"><div><h3>AI control group</h3><p>AI strategy against no-AI baseline</p></div><div className="control-icon"><Bot size={18}/></div></div><div className="control-callout"><div className="callout-label">NO-AI CONTROL P&L</div><strong className={controlPnl>=0?"positive-text":"negative-text"}>{money(controlPnl)}</strong><span>{controls} completed control trades</span></div><div className="comparison-line"><div><span>AI strategy</span><strong className={totalPnl>=0?"positive-text":"negative-text"}>{money(totalPnl)}</strong></div><div><span>No-AI control</span><strong>{money(controlPnl)}</strong></div></div><div className="mini-bar"><span style={{width:`${Math.max(8,Math.min(100,Math.abs(totalPnl)/(Math.abs(totalPnl)+Math.abs(controlPnl)+1)*100))}%`}}/><i style={{width:`${Math.max(8,Math.min(100,Math.abs(controlPnl)/(Math.abs(totalPnl)+Math.abs(controlPnl)+1)*100))}%`}}/></div><button className="panel-link" onClick={()=>setTab("AI vs no-AI")}>Explore AI impact <ArrowUpRight size={15}/></button><div className="research-note"><ShieldCheck size={15}/><span>Control results are hypothetical and do not place orders.</span></div></section>
    </div>
    <section className="panel table-panel"><div className="panel-heading"><div><h3>Recent trades</h3><p>Your latest simulated executions</p></div><button className="panel-link" onClick={()=>setTab("Trade journal")}>View journal <ArrowUpRight size={15}/></button></div><TradeTable trades={recent}/></section>
    <div className="bottom-grid"><section className="panel insight-panel"><div className="panel-heading"><div><h3>Strategy signals</h3><p>Quick read from your current sample</p></div><Sparkles size={17} className="muted-icon"/></div><div className="insight-row"><div className="insight-symbol"><Bot size={16}/></div><div className="insight-copy"><strong>AI decisions recorded</strong><span>{aiSkipped} skip decisions across visible trades</span></div><span className="insight-value">{trades.length ? `${Math.round(aiSkipped/Math.max(1,trades.length)*100)}%` : "—"}</span></div><div className="insight-row"><div className="insight-symbol"><Activity size={16}/></div><div className="insight-copy"><strong>Control group coverage</strong><span>Completed no-AI outcomes stored</span></div><span className="insight-value">{controls}</span></div></section><section className="panel quick-panel"><div className="panel-heading"><div><h3>Workspace status</h3><p>Data & execution safety</p></div><CheckCircle2 size={17} className="positive-text"/></div><div className="status-row"><span>Execution environment</span><strong><i className="tiny-dot green-dot"/> Paper only</strong></div><div className="status-row"><span>Dashboard data</span><strong>{isSupabaseConfigured ? "Supabase configured" : "Preview mode"}</strong></div><div className="status-row"><span>Broker order routing</span><strong>Disabled</strong></div></section></div>
  </>;
}

function TradeTable({ trades }: { trades:PaperTrade[] }) {
  if (!trades.length) return <div className="table-empty">No matching trades found.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Trade / symbol</th><th>Side</th><th>Entry → exit</th><th>Exit reason</th><th>AI decision</th><th>Net P&L</th><th>Timestamp</th></tr></thead><tbody>{trades.map(t=><tr key={t.id}><td><div className="symbol-cell"><span className="symbol-icon">{t.symbol.replace(".NS","").slice(0,2)}</span><div><strong>{t.symbol.replace(".NS","")}</strong><small>#{t.id}</small></div></div></td><td><span className={`side-tag ${t.side==="BUY"?"buy":"sell"}`}>{t.side}</span></td><td><span className="price-pair">{t.entry.toFixed(2)} <span>→</span> {t.exit == null ? "Open" : Number(t.exit).toFixed(2)}</span></td><td><span className="reason-text">{(t.reason ?? (t.status==="open"?"Open position":"—")).replaceAll("_"," ")}</span></td><td><span className={`ai-tag ${t.llm_decision==="take"?"ai-take":t.llm_decision==="skip"?"ai-skip":"ai-na"}`}>{t.llm_decision ?? "—"}</span></td><td className={Number(t.pnl)>=0?"positive-text":"negative-text"}>{t.pnl == null ? "—" : preciseMoney(Number(t.pnl))}</td><td className="date-cell">{formatDate(t.ts)}</td></tr>)}</tbody></table></div>;
}

function Journal({ trades, query, setQuery, sideFilter, setSideFilter }: { trades:PaperTrade[]; query:string; setQuery:(v:string)=>void; sideFilter:string; setSideFilter:(v:string)=>void }) {
  return <section className="panel journal-panel"><div className="journal-toolbar"><div className="search-box"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search symbol, reason or AI decision"/></div><select value={sideFilter} onChange={e=>setSideFilter(e.target.value)} aria-label="Filter side"><option>All sides</option><option>BUY</option><option>SELL</option></select><button className="button-secondary" onClick={()=>{setQuery("");setSideFilter("All sides");}}><X size={15}/> Reset</button></div><div className="panel-heading journal-heading"><div><h3>Trade journal</h3><p>{trades.length} trades match the current filters</p></div><span className="select-chip"><CalendarDays size={14}/> All available dates</span></div><TradeTable trades={trades}/></section>;
}

function AIComparison({ trades, controls, aiPnl, controlPnl, aiSkipped }: { trades:PaperTrade[]; controls:ControlTrade[]; aiPnl:number; controlPnl:number; aiSkipped:number }) {
  const aiWinRate = trades.length ? trades.filter(t=>Number(t.pnl)>0).length/trades.length*100 : 0;
  const controlWinRate = controls.length ? controls.filter(t=>Number(t.pnl)>0).length/controls.length*100 : 0;
  const delta = aiPnl-controlPnl;
  return <><div className="notice research-notice"><ShieldCheck size={16}/><span><strong>Research view, not a live recommendation.</strong> AI and no-AI results must use matched signals, equivalent sizing and completed trades before drawing conclusions.</span></div><div className="metric-grid compare-metrics"><MetricCard label="AI strategy net P&L" value={money(aiPnl)} icon={Bot} sub={`${trades.length} closed trades`}/><MetricCard label="No-AI control P&L" value={money(controlPnl)} icon={Activity} sub={`${controls.length} completed controls`}/><MetricCard label="P&L difference" value={money(delta)} positive={delta>=0} icon={TrendingUp} sub="AI minus control"/><MetricCard label="AI skip decisions" value={String(aiSkipped)} icon={ShieldCheck} sub="Logged AI rejections"/></div><div className="main-grid"><section className="panel"><div className="panel-heading"><div><h3>Strategy comparison</h3><p>Net realized INR after estimated costs</p></div></div><div className="compare-rows"><CompareBar label="AI strategy" value={aiPnl} max={Math.max(Math.abs(aiPnl),Math.abs(controlPnl),1)}/><CompareBar label="No-AI control" value={controlPnl} max={Math.max(Math.abs(aiPnl),Math.abs(controlPnl),1)}/></div><div className="research-note"><CircleHelp size={15}/><span>Comparisons are only as reliable as their matched signals and cost assumptions.</span></div></section><section className="panel"><div className="panel-heading"><div><h3>Quality indicators</h3><p>Use completed records only</p></div></div><div className="status-row"><span>AI strategy win rate</span><strong>{aiWinRate.toFixed(1)}%</strong></div><div className="status-row"><span>No-AI control win rate</span><strong>{controlWinRate.toFixed(1)}%</strong></div><div className="status-row"><span>AI skip count</span><strong>{aiSkipped}</strong></div><div className="status-row"><span>Control sample size</span><strong>{controls.length}</strong></div></section></div><section className="panel table-panel"><div className="panel-heading"><div><h3>Control-group outcomes</h3><p>Hypothetical trades using the original breakout exits</p></div><span className="ai-tag ai-na">NO-AI BASELINE</span></div><div className="table-scroll"><table><thead><tr><th>Symbol</th><th>Side</th><th>AI decision</th><th>Exit reason</th><th>Entry → exit</th><th>Control P&L</th><th>Closed at</th></tr></thead><tbody>{controls.map(t=><tr key={t.id}><td><strong>{t.symbol.replace(".NS","")}</strong></td><td><span className={`side-tag ${t.side==="BUY"?"buy":"sell"}`}>{t.side ?? "—"}</span></td><td><span className={`ai-tag ${t.ai_decision==="take"?"ai-take":t.ai_decision==="skip"?"ai-skip":"ai-na"}`}>{t.ai_decision ?? "—"}</span></td><td>{(t.exit_reason??"—").replaceAll("_"," ")}</td><td>{t.entry_price?.toFixed(2) ?? "—"} → {t.exit_price?.toFixed(2) ?? "—"}</td><td className={Number(t.pnl)>=0?"positive-text":"negative-text"}>{t.pnl==null?"—":preciseMoney(Number(t.pnl))}</td><td className="date-cell">{formatDate(t.ts)}</td></tr>)}</tbody></table></div></section></>;
}
function CompareBar({label,value,max}:{label:string;value:number;max:number}) { return <div className="compare-bar-row"><div><span>{label}</span><strong className={value>=0?"positive-text":"negative-text"}>{money(value)}</strong></div><div className="compare-track"><span className={value>=0?"bar-positive":"bar-negative"} style={{width:`${Math.max(3,Math.abs(value)/max*100)}%`}}/></div></div>; }

function ResearchPage() {
  return <><div className="metric-grid"><MetricCard label="Saved backtest runs" value="—" icon={BarChart3} sub="Connected to backtest_runs when available"/><MetricCard label="Strategy variants" value="4" icon={SlidersHorizontal} sub="Alternative exit rules tracked"/><MetricCard label="Out-of-sample results" value="—" icon={TrendingUp} sub="No values inferred"/><MetricCard label="Evidence status" value="Collecting" icon={Clock3} sub="Prospective paper observations"/></div><section className="panel empty-research"><div className="empty-research-icon"><BarChart3 size={23}/></div><h3>Backtest research workspace</h3><p>Historical runs will appear here once the dashboard is connected to saved backtest results. Paper performance and historical backtests will remain separate to avoid mixing evidence.</p><span className="ai-tag ai-na">NO BACKTEST DATA IN THIS VIEW YET</span></section></>;
}
function RiskPage({trades,openTrades,totalPnl}:{trades:PaperTrade[];openTrades:PaperTrade[];totalPnl:number}) {
  const exposure=openTrades.reduce((s,t)=>s+Number(t.qty)*Number(t.last_price??t.entry),0);
  const losses=trades.filter(t=>Number(t.pnl)<0).length;
  return <><div className="metric-grid"><MetricCard label="Open positions" value={String(openTrades.length)} icon={Activity} sub="Unclosed paper positions"/><MetricCard label="Marked exposure" value={money(exposure)} icon={Wallet} sub="Based on last known marks"/><MetricCard label="Realized P&L" value={money(totalPnl)} positive={totalPnl>=0} icon={TrendingUp} sub="Estimated exits excluded"/><MetricCard label="Losing trades" value={String(losses)} icon={ShieldCheck} sub="Closed trades only"/></div><div className="main-grid"><section className="panel"><div className="panel-heading"><div><h3>Risk guardrails</h3><p>Configured strategy limits</p></div><ShieldCheck size={17} className="positive-text"/></div><div className="status-row"><span>Risk per trade</span><strong>1% of capital</strong></div><div className="status-row"><span>Daily loss cap</span><strong>3% of capital</strong></div><div className="status-row"><span>Maximum entries per day</span><strong>3</strong></div><div className="status-row"><span>Order environment</span><strong className="positive-text">Paper only</strong></div></section><section className="panel"><div className="panel-heading"><div><h3>Open position marks</h3><p>Latest values reported by the bot</p></div></div>{openTrades.length ? openTrades.map(t=><div className="insight-row" key={t.id}><div className="symbol-icon">{t.symbol.slice(0,2)}</div><div className="insight-copy"><strong>{t.symbol.replace(".NS","")} · {t.side}</strong><span>{t.qty} shares · last mark {t.last_price?.toFixed(2)??"not available"}</span></div><span className="insight-value">{t.last_price_ts?formatDate(t.last_price_ts):"—"}</span></div>):<div className="empty-inline"><CheckCircle2 size={18}/><span>No open positions reported.</span></div>}</section></div></>;
}

export default App;