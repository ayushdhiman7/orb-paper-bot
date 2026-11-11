import type { PaperTrade } from "../lib/api";
import { inr, reason, signedInr, sym, tone, when } from "../lib/format";
import { unrealized } from "../lib/stats";
import { Badge, Empty } from "./ui";

type Props = {
  trades: PaperTrade[];
  onExit?: (trade: PaperTrade) => void;
  exitStatus?: Record<string, string>;
};

export function TradeList({ trades, onExit, exitStatus = {} }: Props) {
  if (!trades.length) return <Empty title="No trades" hint="Nothing matches this view yet." />;
  return (
    <ul className="trade-list">
      {trades.map(t => {
        const open = t.status === "open";
        const pnl = open ? unrealized(t) : t.pnl == null ? null : Number(t.pnl);
        const status = exitStatus[String(t.id)];
        return (
          <li className="trade" key={t.id}>
            <div className="trade-main">
              <span className="avatar">{sym(t.symbol).slice(0, 2)}</span>
              <div className="trade-id">
                <strong>{sym(t.symbol)}</strong>
                <small>#{t.id} · {when(t.ts)}</small>
              </div>
              <Badge kind={t.side === "BUY" ? "buy" : "sell"}>{t.side}</Badge>
              <strong className={`trade-pnl ${tone(pnl)}`}>{pnl == null ? "—" : signedInr(pnl)}</strong>
            </div>
            <div className="trade-meta">
              <span>{Number(t.entry).toFixed(2)} → {open ? (t.last_price != null ? `${Number(t.last_price).toFixed(2)} live` : "open") : Number(t.exit).toFixed(2)}</span>
              <span>{t.qty} qty · {inr(Number(t.qty) * Number(t.entry))}</span>
              <span>{open ? "open position" : reason(t.reason)}</span>
              {t.llm_decision && <Badge kind={t.llm_decision === "take" ? "take" : "skip"}>AI {t.llm_decision}</Badge>}
              {t.exit_estimated && <Badge kind="warn">estimated exit</Badge>}
            </div>
            {open && onExit && (
              <div className="trade-actions">
                <button className="btn danger" disabled={status?.startsWith("Submitting") || status?.startsWith("Exit queued")} onClick={() => onExit(t)}>
                  Exit paper position
                </button>
                {status && <small>{status}</small>}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
