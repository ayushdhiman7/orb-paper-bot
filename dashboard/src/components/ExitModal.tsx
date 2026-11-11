import { useState } from "react";
import type { PaperTrade } from "../lib/api";
import { sym } from "../lib/format";

export function ExitModal({ trade, onCancel, onConfirm }: { trade: PaperTrade; onCancel: () => void; onConfirm: (token: string) => void }) {
  const [token, setToken] = useState("");
  return (
    <div className="backdrop" role="presentation">
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="exit-title">
        <h2 id="exit-title">Exit {sym(trade.symbol)}?</h2>
        <p>The bot closes this paper position at the next fresh price. No broker order is sent.</p>
        <label>
          Control token
          <input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} placeholder="Dashboard control token" />
        </label>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn danger" disabled={!token.trim()} onClick={() => onConfirm(token.trim())}>Confirm exit</button>
        </div>
      </section>
    </div>
  );
}
