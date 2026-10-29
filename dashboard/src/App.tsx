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
import type { BacktestRun, ControlTrade, PaperTrade } from "./lib/supabase";

type Tab = "Overview" | "Trade journal" | "AI vs no-AI" | "Backtests" | "Risk monitor";
type DashboardData = { trades: PaperTrade[]; controls: ControlTrade[]; backtests: BacktestRun[]; backtestsError?: string | null };

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
  const [data, setData] = useState<DashboardData>({ trades: demoTrades, controls: demoControls, backtests: [] });
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
      setData({ trades: [], controls: [], backtests: [] });
      setDemo(false);
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
        {error && <div className="notice error-notice"><Database size={16}/><span><strong>Could not refresh trade data.</strong> {error} Live records are hidden rather than replaced with sample numbers.</span><button className="text-button" onClick={() => void refresh()}>Retry</button></div>}
        {data.backtestsError && !demo && <div className="notice error-notice"><Database size={16}/><span><strong>Backtest history unavailable.</strong> {data.backtestsError} Trade analytics can still load independently.</span></div>}
        {!demo && !error && data.trades.length === 0 && <div className="notice error-notice"><ShieldCheck size={16}/><span><strong>No paper-trade rows are visible to this dashboard.</strong> This may mean the table is empty or Supabase row-level security is blocking the browser key. Verify access using an owner-only policy; do not enable public read access just to populate the UI.</span></div>}
        {tab === "Overview" && <Overview trades={closedTrades} totalPnl={totalPnl} matchedAiPnl={matchedAiPnl} winRate={winRate} openCount={openTrades.length} aiSkipped={aiSkipped} equity={equity} controls={matchedControls.length} controlPnl={controlPnl} setTab={setTab} activeRange={activeRange} setActiveRange={setActiveRange}/>}
        {tab === "Trade journal" && <Journal trades={filteredTrades} query={query} setQuery={setQuery} sideFilter={sideFilter} setSideFilter={setSideFilter}/>}
        {tab === "AI vs no-AI" && <AIComparison trades={closedTrades} controls={controlTrades} aiSkipped={aiSkipped}/>}
        {tab === "Backtests" && <ResearchPage runs={data.backtests}/>} 
        {tab === "Risk monitor" && <RiskPage trades={closedTrades} openTrades={openTrades} totalPnl={totalPnl}/>}
        <footer className="footer"><span><ShieldCheck size={14}/> Paper trading only · No broker orders</span><span>ORB Terminal <b>v0.1</b> <span className="footer-sep">·</span> Data source: {demo ? "sample preview" : "Supabase"}</span></footer>
      </div>
    </main>
  </div>;
}

function MetricCard({ label, value, change, positive, icon: Icon, sub }: { label:string; value:string; change?:string; positive?:boolean; icon:typeof Wallet; sub:string }) {
  return <div className="metric-card"><div className="metric-top"><span>{label}</span><div className="metric-icon"><Icon size={17}/></div></div><div className="metric-value">{value}</div><div className="metric-bottom">{change && <span className={positive ? "change positive" : "change negative"}>{positive ? <ArrowUpRight size={13}/> : <ArrowDownRight size={13}/>} {change}</span>}<span className="metric-sub">{sub}</span></div></div>;
}

function Overview({ trades, totalPnl, matchedAiPnl, winRate, openCount, aiSkipped, equity, controls, controlPnl, setTab, activeRange, setActiveRange }: { trades:PaperTrade[]; totalPnl:number; matchedAiPnl:number; winRate:number; openCount:number; aiSkipped:number; equity:{day:string;pnl:number}[]; controls:number; controlPnl:number; setTab:(t:Tab)=>void; activeRange:string; setActiveRange:(v:string)=>void }) {
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
      <section className="panel control-panel"><div className="panel-heading"><div><h3>AI control group</h3><p>AI strategy against no-AI baseline</p></div><div className="control-icon"><Bot size={18}/></div></div><div className="control-callout"><div className="callout-label">NO-AI CONTROL P&L</div><strong className={controlPnl>=0?"positive-text":"negative-text"}>{money(controlPnl)}</strong><span>{controls} completed control trades</span></div><div className="comparison-line"><div><span>AI strategy (matched)</span><strong className={matchedAiPnl>=0?"positive-text":"negative-text"}>{money(matchedAiPnl)}</strong></div><div><span>No-AI control (matched)</span><strong>{money(controlPnl)}</strong></div></div><div className="mini-bar"><span style={{width:`${Math.max(8,Math.min(100,Math.abs(matchedAiPnl)/(Math.abs(matchedAiPnl)+Math.abs(controlPnl)+1)*100))}%`}}/><i style={{width:`${Math.max(8,Math.min(100,Math.abs(controlPnl)/(Math.abs(matchedAiPnl)+Math.abs(controlPnl)+1)*100))}%`}}/></div><button className="panel-link" onClick={()=>setTab("AI vs no-AI")}>Explore AI impact <ArrowUpRight size={15}/></button><div className="research-note"><ShieldCheck size={15}/><span>Control results are hypothetical and do not place orders.</span></div></section>
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
function RiskPage({trades,openTrades,totalPnl}:{trades:PaperTrade[];openTrades:PaperTrade[];totalPnl:number}) {
  const exposure=openTrades.reduce((s,t)=>s+Number(t.qty)*Number(t.last_price??t.entry),0);
  const losses=trades.filter(t=>Number(t.pnl)<0).length;
  return <><div className="metric-grid"><MetricCard label="Open positions" value={String(openTrades.length)} icon={Activity} sub="Unclosed paper positions"/><MetricCard label="Marked exposure" value={money(exposure)} icon={Wallet} sub="Based on last known marks"/><MetricCard label="Realized P&L" value={money(totalPnl)} positive={totalPnl>=0} icon={TrendingUp} sub="Estimated exits excluded"/><MetricCard label="Losing trades" value={String(losses)} icon={ShieldCheck} sub="Closed trades only"/></div><div className="main-grid"><section className="panel"><div className="panel-heading"><div><h3>Risk guardrails</h3><p>Configured strategy limits</p></div><ShieldCheck size={17} className="positive-text"/></div><div className="status-row"><span>Risk per trade</span><strong>Configured in bot env</strong></div><div className="status-row"><span>Daily loss cap</span><strong>Configured in bot env</strong></div><div className="status-row"><span>Maximum entries per day</span><strong>Configured in bot env</strong></div><div className="status-row"><span>Order environment</span><strong className="positive-text">Paper only</strong></div></section><section className="panel"><div className="panel-heading"><div><h3>Open position marks</h3><p>Latest values reported by the bot</p></div></div>{openTrades.length ? openTrades.map(t=><div className="insight-row" key={t.id}><div className="symbol-icon">{t.symbol.slice(0,2)}</div><div className="insight-copy"><strong>{t.symbol.replace(".NS","")} · {t.side}</strong><span>{t.qty} shares · last mark {t.last_price?.toFixed(2)??"not available"}</span></div><span className="insight-value">{t.last_price_ts?formatDate(t.last_price_ts):"—"}</span></div>):<div className="empty-inline"><CheckCircle2 size={18}/><span>No open positions reported.</span></div>}</section></div></>;
}

export default App;