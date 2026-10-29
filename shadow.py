"""
Shadow ledger: what WOULD have happened to each real paper trade under alternative exit rules.

The baseline strategy stays frozen and untouched. Each baseline trade (same entry, same prices, same cost model)
is replayed live against these variants; results are only recorded, never acted on:
  breakeven_1R  once the trade has been 1R in profit, stop moves to the entry price
  giveback_50   once 1R in profit, exit if open profit falls below half of the best profit seen
  trail_1R      once 1R in profit, stop trails 1R behind the best price
  ai_exit       the first time the AI (AI_EXITS=shadow) advised "exit"
Every variant also keeps the original stop and target. A variant still open when the baseline closes is closed at
the baseline's exit price. No network, no bot imports: fee/fill functions are passed in so tests stay offline.
"""
from dataclasses import dataclass, field

VARIANTS = ("breakeven_1R", "giveback_50", "trail_1R", "ai_exit")


@dataclass
class _Sim:
    exit_price: float = None
    exit_reason: str = None
    exit_ts: object = None


@dataclass
class _Track:
    side: str
    qty: int
    entry: float
    stop: float
    target: float
    entry_fee: float
    peak: float
    row_id: object
    sims: dict = field(default_factory=lambda: {v: _Sim() for v in VARIANTS})


class ShadowLedger:
    def __init__(self, fee_fn, fill_fn):
        self.fee_fn, self.fill_fn = fee_fn, fill_fn      # fee_for_notional, adverse_fill
        self.tracks = {}

    def open(self, symbol, pos):
        self.tracks[symbol] = _Track(pos.side, pos.qty, pos.entry, pos.stop, pos.target, pos.entry_fee,
                                     pos.peak if pos.peak is not None else pos.entry, pos.row_id)

    def _profit(self, t, price):
        return (price - t.entry) * (1 if t.side == "BUY" else -1)

    def _set(self, t, name, price, reason, now):
        s = t.sims[name]
        if s.exit_price is None:
            s.exit_price, s.exit_reason, s.exit_ts = price, reason, now

    def tick(self, symbol, price, now):
        t = self.tracks.get(symbol)
        if t is None:
            return
        d = 1 if t.side == "BUY" else -1
        if (price - t.peak) * d > 0:
            t.peak = price
        risk = abs(t.entry - t.stop)
        best = self._profit(t, t.peak)
        for name in ("breakeven_1R", "giveback_50", "trail_1R"):
            if t.sims[name].exit_price is not None:
                continue
            if (price - t.stop) * d <= 0:
                self._set(t, name, price, "stop_loss", now)
            elif (price - t.target) * d >= 0:
                self._set(t, name, price, "target", now)
            elif best >= risk:
                if name == "breakeven_1R" and (price - t.entry) * d <= 0:
                    self._set(t, name, price, "breakeven", now)
                elif name == "giveback_50" and self._profit(t, price) < best / 2:
                    self._set(t, name, price, "giveback", now)
                elif name == "trail_1R" and (price - (t.peak - d * risk)) * d <= 0:
                    self._set(t, name, price, "trail", now)

    def ai_exit(self, symbol, price, now, note=None):
        """First AI "exit" advice for this trade; the AI's reason is kept so it can be reviewed later."""
        t = self.tracks.get(symbol)
        if t is not None:
            self._set(t, "ai_exit", price, ("ai_exit: " + str(note)[:200]) if note else "ai_exit", now)

    def close(self, symbol, baseline_price, baseline_pnl, now):
        """Baseline trade ended: finish every variant and return one row per variant (for logging)."""
        t = self.tracks.pop(symbol, None)
        if t is None:
            return []
        d = 1 if t.side == "BUY" else -1
        rows = []
        for name, s in t.sims.items():
            if s.exit_price is None:
                self._set(t, name, baseline_price, "baseline_exit", now)
            fill = self.fill_fn(s.exit_price, d, False)
            pnl = (fill - t.entry) * t.qty * d - t.entry_fee - self.fee_fn(t.qty * fill)
            rows.append({"trade_id": t.row_id, "symbol": symbol, "variant": name, "exit_price": round(fill, 2),
                         "exit_reason": s.exit_reason, "pnl": round(pnl, 2), "baseline_pnl": baseline_pnl,
                         "ts": (s.exit_ts or now).isoformat()})
        return rows

@dataclass
class _ControlTrack:
    """A no-AI control trade that is independent of the actual AI-managed position."""
    signal_id: str
    side: str
    qty: int
    entry: float
    stop: float
    target: float
    entry_fee: float
    opened_at: object
    ai_decision: str
    ai_reason: str
    trade_id: object = None


class NoAIControlLedger:
    """Replay every eligible signal with original stop/target, independent of AI decisions/exits.

    Control tracks are not removed when the real paper trade closes. They finish only at their
    own stop, target, or the explicit end-of-session square-off.
    """
    def __init__(self, fee_fn, fill_fn):
        self.fee_fn, self.fill_fn = fee_fn, fill_fn
        self.tracks = {}

    def open(self, symbol, pos, signal_id, ai_decision=None, ai_reason=None):
        self.tracks[symbol] = _ControlTrack(
            signal_id=signal_id, side=pos.side, qty=pos.qty, entry=pos.entry,
            stop=pos.stop, target=pos.target, entry_fee=pos.entry_fee,
            opened_at=pos.opened_at, ai_decision=ai_decision or "not_available",
            ai_reason=(ai_reason or "")[:200], trade_id=pos.row_id,
        )

    def link_trade(self, symbol, trade_id):
        track = self.tracks.get(symbol)
        if track is not None:
            track.trade_id = trade_id

    def _finish(self, symbol, price, reason, now):
        t = self.tracks.pop(symbol, None)
        if t is None:
            return []
        direction = 1 if t.side == "BUY" else -1
        fill = self.fill_fn(price, direction, False)
        pnl = (fill - t.entry) * t.qty * direction - t.entry_fee - self.fee_fn(t.qty * fill)
        return [{
            "trade_id": t.trade_id,
            "signal_id": t.signal_id,
            "symbol": symbol,
            "variant": "no_ai_control",
            "side": t.side,
            "qty": t.qty,
            "entry_price": round(t.entry, 2),
            "exit_price": round(fill, 2),
            "entry_ts": t.opened_at.isoformat(),
            "exit_reason": reason,
            "ai_decision": t.ai_decision,
            "ai_reason": t.ai_reason,
            "pnl": round(pnl, 2),
            "baseline_pnl": None,
            "ts": now.isoformat(),
        }]

    def tick(self, symbol, price, now):
        t = self.tracks.get(symbol)
        if t is None:
            return []
        if (t.side == "BUY" and price <= t.stop) or (t.side == "SELL" and price >= t.stop):
            return self._finish(symbol, price, "stop_loss", now)
        if (t.side == "BUY" and price >= t.target) or (t.side == "SELL" and price <= t.target):
            return self._finish(symbol, price, "target", now)
        return []

    def close(self, symbol, price, now, reason="square_off"):
        return self._finish(symbol, price, reason, now)

    def close_all(self, prices, now, reason="square_off"):
        rows = []
        for symbol in list(self.tracks):
            price = prices.get(symbol)
            if price is not None:
                rows.extend(self.close(symbol, price, now, reason))
        return rows

