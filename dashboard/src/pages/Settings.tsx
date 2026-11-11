import { useEffect, useState } from "react";
import { loadBotSettings, saveBotSettings } from "../lib/api";
import type { BotSettings } from "../lib/api";
import { Notice, Panel } from "../components/ui";

type NumKey = Exclude<keyof BotSettings, "square_off_time" | "emergency_stop" | "paper_only" | "sentiment_enabled" | "ai_position_management_enabled">;
type Field = { key: NumKey; label: string; min: number; max: number; step: number; unit?: string };

const GROUPS: { title: string; note: string; fields: Field[] }[] = [
  { title: "Schedule & AI", note: "How often the runner scans and reviews.", fields: [
    { key: "scan_interval_seconds", label: "Scan interval", min: 60, max: 900, step: 30, unit: "s" },
    { key: "position_review_seconds", label: "Position review", min: 60, max: 1800, step: 60, unit: "s" },
    { key: "ai_position_min_confidence", label: "AI confidence minimum", min: 0, max: 1, step: 0.05 },
    { key: "stale_quote_seconds", label: "Stale quote limit", min: 10, max: 90, step: 5, unit: "s" } ] },
  { title: "Risk limits", note: "Re-checked by the deterministic risk engine.", fields: [
    { key: "risk_per_trade_pct", label: "Risk per trade", min: 0.1, max: 1, step: 0.1, unit: "%" },
    { key: "daily_loss_cap_pct", label: "Daily loss cap", min: 0.5, max: 2, step: 0.1, unit: "%" },
    { key: "max_open_positions", label: "Max open positions", min: 1, max: 2, step: 1 },
    { key: "max_trades_per_day", label: "Max trades per day", min: 1, max: 3, step: 1 } ] },
  { title: "Position protection", note: "Measured in initial risk units (R).", fields: [
    { key: "breakeven_r", label: "Move toward breakeven", min: 0.5, max: 2, step: 0.1, unit: "R" },
    { key: "profit_protection_r", label: "Protection starts", min: 1, max: 3, step: 0.1, unit: "R" },
    { key: "protected_profit_r", label: "Profit to protect", min: 0.1, max: 1.5, step: 0.1, unit: "R" },
    { key: "trailing_start_r", label: "Trailing starts", min: 1.5, max: 4, step: 0.1, unit: "R" } ] },
];

export default function Settings() {
  const [s, setS] = useState<BotSettings | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => { loadBotSettings().then(d => setS(d.settings)).catch(e => setErr(e instanceof Error ? e.message : "Unable to load settings.")); }, []);
  if (!s) return err ? <Notice kind="error">{err}</Notice> : <p className="footnote">Loading settings…</p>;

  const save = async () => {
    if (!token.trim()) { setErr("Enter the control token to save."); return; }
    setBusy(true); setErr(""); setMsg("");
    try {
      const { paper_only: _locked, ...editable } = s;
      const result = await saveBotSettings(editable, token.trim());
      setS(result.settings); setMsg(`Saved as version ${result.version}. The bot applies it within about 15 seconds.`);
    } catch (e) { setErr(e instanceof Error ? e.message : "Save failed."); }
    finally { setToken(""); setBusy(false); }
  };

  return (
    <>
      {GROUPS.map(g => (
        <Panel key={g.title} title={g.title} note={g.note}>
          <div className="fields">{g.fields.map(f => (
            <label key={f.key}>{f.label}{f.unit ? ` (${f.unit})` : ""}
              <input type="number" min={f.min} max={f.max} step={f.step} value={Number(s[f.key])}
                onChange={e => setS({ ...s, [f.key]: Number(e.target.value) })} />
            </label>))}
            {g.title === "Position protection" && (
              <label>Square-off time (IST)
                <input type="time" min="15:00" max="15:25" value={s.square_off_time} onChange={e => setS({ ...s, square_off_time: e.target.value })} />
              </label>)}
          </div>
        </Panel>
      ))}
      <Panel title="Features">
        <label className="toggle"><input type="checkbox" checked={s.ai_position_management_enabled} onChange={e => setS({ ...s, ai_position_management_enabled: e.target.checked })} />
          <span><strong>AI position management</strong><small>Validated HOLD / stop / target / exit actions on open positions.</small></span></label>
        <label className="toggle"><input type="checkbox" checked={s.sentiment_enabled} onChange={e => setS({ ...s, sentiment_enabled: e.target.checked })} />
          <span><strong>News sentiment context</strong><small>Context only. It never creates or vetoes a breakout.</small></span></label>
      </Panel>
      <Panel title="Emergency stop" note="Halts new entries and closes every open paper position on fresh quotes.">
        <label className="toggle danger"><input type="checkbox" checked={s.emergency_stop}
          onChange={e => { if (!e.target.checked || window.confirm("Halt entries and close all open paper positions?")) setS({ ...s, emergency_stop: e.target.checked }); }} />
          <span><strong>Emergency stop</strong><small>Applies when saved.</small></span></label>
      </Panel>
      <Panel title="Save">
        <p className="footnote">Paper-only execution is locked. This dashboard cannot enable live orders.</p>
        <label className="token">Control token
          <input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} placeholder="Required to save" />
        </label>
        {err && <Notice kind="error">{err}</Notice>}
        {msg && <Notice kind="ok">{msg}</Notice>}
        <div className="modal-actions">
          <button className="btn" onClick={() => { setErr(""); setMsg(""); loadBotSettings().then(d => setS(d.settings)).catch(e => setErr(e.message)); }}>Reload</button>
          <button className="btn primary" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save settings"}</button>
        </div>
      </Panel>
    </>
  );
}
