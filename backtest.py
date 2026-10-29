"""
Backtest + strategy lab for the ORB (opening-range breakout) rules, on free Yahoo 5-minute NSE data.

Follows the backtest-expert method: realistic costs + slippage, a parameter grid (look for a plateau,
not a spike), and a train/test split so the "best" settings are judged on days they never saw.

  python backtest.py        -> baseline backtest of the bot's rules (saved to the dashboard's Backtest tab)
  python backtest.py lab    -> tests several rule variants (filters) and a no-cost check

Yahoo only serves ~60 days of 5-minute history, so this is a SMOKE TEST, not proof of an edge.
Run from the GitHub Actions tab: "backtest" or "lab" -> Run workflow.
"""
import itertools
import os
import sys
import warnings
from datetime import time as dtime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
IST = ZoneInfo("Asia/Kolkata")

SYMBOLS = os.getenv("SYMBOLS", "RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS").split(",")
CAPITAL = float(os.getenv("CAPITAL", "14000"))
RISK_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
COST_PCT = float(os.getenv("COST_PCT", "0.10"))          # total entry + exit transaction costs, % notional
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.05"))  # per side, % of price
MAX_TRADES = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
DAILY_CAP_PCT = float(os.getenv("DAILY_LOSS_CAP_PCT", "3.0"))
TRAIN_FRACTION = 0.7

STOPS = [0.5, 0.75, 1.0, 1.25, 1.5]   # stop-loss % (baseline 1.0)
RRS = [1.0, 1.5, 2.0]                 # target as a multiple of risk (baseline 1.5)
BASE = (1.0, 1.5)

OPEN, SQUARE_OFF, NO_NEW = dtime(9, 15), dtime(15, 15), dtime(14, 30)
BAR = timedelta(minutes=5)

DEFAULT_OPTS = {"range_min": 15, "vol_mult": None, "gap": False, "long_only": False,
                "min_rng": None, "max_rng": None, "slip_pct": None}

# Variants tried by the lab. Kept small on purpose: every extra variant tried on the same 60 days
# raises the odds that one looks good by luck.
VARIANTS = [
    ("Baseline (as the bot)", {}),
    ("30-minute opening range", {"range_min": 30}),
    ("Volume spike (1.5x)", {"vol_mult": 1.5}),
    ("Trade with the gap", {"gap": True}),
    ("Long only", {"long_only": True}),
    ("Volume spike + gap", {"vol_mult": 1.5, "gap": True}),
    ("Skip wide ranges (>1%)", {"max_rng": 1.0}),
]


def load_data(symbols):
    out = {}
    for s in symbols:
        try:
            df = yf.Ticker(s).history(period="60d", interval="5m")
        except Exception as e:
            print(f"[warn] {s}: {e}")
            continue
        if df.empty:
            print(f"[warn] no data for {s}")
            continue
        df.index = df.index.tz_convert(IST)
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        out[s] = df[cols]
    return out


def _mask(index, lo, hi):
    return np.array([lo <= t < hi for t in index.time])


def prev_closes(df):
    """Map each trading day to the previous trading day's last close."""
    last = df.groupby(df.index.date)["Close"].last()
    days = list(last.index)
    return {days[i]: float(last.iloc[i - 1]) for i in range(1, len(days))}


_CACHE = {}


def _grouped(sym, df):
    key = (sym, id(df))
    if key not in _CACHE:
        _CACHE[key] = ({d: x for d, x in df.groupby(df.index.date)}, prev_closes(df))
    return _CACHE[key]


def find_signal(symbol, bars, stop_pct, rr, opts=None, prev_close=None):
    """First breakout of the day for one stock. Returns a trade dict (assuming it is taken) or None."""
    o = {**DEFAULT_OPTS, **(opts or {})}
    end_min = OPEN.hour * 60 + OPEN.minute + int(o["range_min"])
    range_end = dtime(end_min // 60, end_min % 60)
    rng = bars[_mask(bars.index, OPEN, range_end)]
    if len(rng) < max(2, int(o["range_min"]) // 5 - 1):
        return None
    hi, lo = rng["High"].max(), rng["Low"].min()
    width = (hi - lo) / lo * 100
    if o["min_rng"] is not None and width < o["min_rng"]:
        return None
    if o["max_rng"] is not None and width > o["max_rng"]:
        return None
    gap = None if prev_close is None else float(bars["Open"].iloc[0]) - prev_close
    after = bars[_mask(bars.index, range_end, SQUARE_OFF)]
    slip = (SLIPPAGE_PCT if o["slip_pct"] is None else o["slip_pct"]) / 100
    for i in range(len(after)):
        ts, row = after.index[i], after.iloc[i]
        if ts.time() >= NO_NEW:
            break
        close = float(row["Close"])
        side = 1 if close > hi else -1 if close < lo else 0
        if not side:
            continue
        if o["long_only"] and side == -1:
            continue
        if o["gap"] and (gap is None or (side == 1 and gap <= 0) or (side == -1 and gap >= 0)):
            continue
        if o["vol_mult"] and "Volume" in bars.columns:
            prior = bars[bars.index < ts]["Volume"].tail(12)
            if len(prior) >= 3 and prior.mean() > 0 and float(row["Volume"]) <= o["vol_mult"] * prior.mean():
                continue
        entry = close * (1 + side * slip)
        stop = entry * (1 - side * stop_pct / 100)
        target = entry + side * abs(entry - stop) * rr
        exit_price, reason, exit_ts = None, "square_off", ts
        mark_path = []
        for j in range(i + 1, len(after)):
            r2, ts2 = after.iloc[j], after.index[j]
            exit_ts = ts2
            mark_price = float(r2["Close"])
            if side == 1:
                if r2["Low"] <= stop:
                    exit_price, reason = stop, "stop"
                    mark_price = stop
                    mark_path.append((ts2 + BAR, mark_price))
                    break
                if r2["High"] >= target:
                    exit_price, reason = target, "target"
                    mark_price = target
                    mark_path.append((ts2 + BAR, mark_price))
                    break
            else:
                if r2["High"] >= stop:
                    exit_price, reason = stop, "stop"
                    mark_price = stop
                    mark_path.append((ts2 + BAR, mark_price))
                    break
                if r2["Low"] <= target:
                    exit_price, reason = target, "target"
                    mark_price = target
                    mark_path.append((ts2 + BAR, mark_price))
                    break
            mark_path.append((ts2 + BAR, mark_price))
        if exit_price is None:
            exit_price = float(after.iloc[-1]["Close"]) if len(after) > i + 1 else close
            exit_ts = after.index[-1] if len(after) > i + 1 else ts
        exit_fill = exit_price * (1 - side * slip)
        return {"symbol": symbol, "side": side, "entry": entry, "stop": stop, "exit_fill": exit_fill,
                "reason": reason, "entry_time": ts + BAR, "exit_time": exit_ts + BAR,
                "mark_path": mark_path}
    return None


def run_day(signals, cost_pct=None):
    """Apply portfolio rules chronologically, including mark-to-market loss-cap checks."""
    cost_pct = COST_PCT if cost_pct is None else cost_pct
    signals = sorted(signals, key=lambda s: s["entry_time"])
    cash, trades, open_, taken = CAPITAL, [], {}, 0
    side_cost_pct = cost_pct / 2.0
    loss_limit = CAPITAL * DAILY_CAP_PCT / 100.0

    # Build a single event timeline. Intraday marks are processed before entries
    # at the same timestamp, so a breach cannot be ignored by a simultaneous signal.
    events = []
    for idx, signal in enumerate(signals):
        for ts, price in signal.get("mark_path", []):
            events.append((ts, 0, "mark", idx, float(price)))
        events.append((signal["entry_time"], 1, "entry", idx, None))
        events.append((signal["exit_time"], 2, "exit", idx, None))
    events.sort(key=lambda event: (event[0], event[1]))

    marked_prices = {}
    realized_pnl = 0.0
    halted = False
    for ts, _, kind, idx, price in events:
        signal = signals[idx]
        key = idx

        if kind == "mark":
            if key in open_:
                marked_prices[key] = price
            # Check total daily P&L against all open positions at every available mark.
            marked_pnl = realized_pnl
            for open_key, trade in open_.items():
                mark = marked_prices.get(open_key, trade["entry"])
                side = trade["side"]
                # Mark the open position at an estimated adverse exit fill, matching bot.py.
                mark_exit_fill = mark * (1 - side * SLIPPAGE_PCT / 100.0)
                gross_unrealized = (mark_exit_fill - trade["entry"]) * trade["qty"] * side
                exit_notional = max(0.0, trade["value"] + gross_unrealized * side)
                exit_fee = exit_notional * side_cost_pct / 100.0
                marked_pnl += gross_unrealized - trade["entry_fee"] - exit_fee
            if marked_pnl <= -loss_limit:
                halted = True
            continue

        if kind == "entry":
            if halted or taken >= MAX_TRADES:
                continue
            per_share = abs(signal["entry"] - signal["stop"])
            if per_share <= 0:
                continue
            qty_by_risk = int((CAPITAL * RISK_PCT / 100) // per_share)
            qty_by_cash = int(max(cash, 0) // (signal["entry"] * (1 + side_cost_pct / 100)))
            qty = min(qty_by_risk, qty_by_cash)
            if qty < 1:
                continue
            value = qty * signal["entry"]
            entry_fee = value * side_cost_pct / 100.0
            cash -= value + entry_fee
            if cash < -1e-6:
                raise RuntimeError("cash went negative: sizing bug")
            taken += 1
            trade = {
                "symbol": signal["symbol"], "net": 0.0, "gross": 0.0,
                "value": value, "entry_fee": entry_fee, "exit_fee": 0.0,
                "exit_time": signal["exit_time"], "reason": signal["reason"],
                "side": signal["side"], "qty": qty, "entry": signal["entry"],
                "entry_time": signal["entry_time"], "day": signal.get("day"),
            }
            open_[key] = trade
            marked_prices[key] = signal["entry"]
            trades.append(trade)
            continue

        if kind == "exit" and key in open_:
            trade = open_.pop(key)
            gross = (signal["exit_fill"] - trade["entry"]) * trade["qty"] * trade["side"]
            exit_notional = max(0.0, trade["value"] + gross * trade["side"])
            exit_fee = exit_notional * side_cost_pct / 100.0
            net = gross - trade["entry_fee"] - exit_fee
            trade.update({"gross": gross, "exit_fee": exit_fee, "net": net})
            cash += trade["value"] + gross - exit_fee
            realized_pnl += net
            marked_prices.pop(key, None)

    return trades


def simulate(data, days, stop_pct, rr, opts=None, cost_pct=None):
    grouped = {sym: _grouped(sym, df) for sym, df in data.items()}
    trades = []
    for day in days:
        sigs = []
        for sym, (by_day, prevs) in grouped.items():
            bars = by_day.get(day)
            if bars is None or bars.empty:
                continue
            sig = find_signal(sym, bars, stop_pct, rr, opts, prevs.get(day))
            if sig:
                sigs.append(sig)
        for t in run_day(sigs, cost_pct):
            t["day"] = day
            trades.append(t)
    return trades


def metrics(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0, "win": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "exp": 0.0, "pf": 0.0, "total": 0.0, "maxdd": 0.0}
    pnl = np.array([t["net"] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gl = -losses.sum()
    equity = np.cumsum(pnl)
    return {"n": n, "win": len(wins) / n * 100,
            "avg_win": float(wins.mean()) if len(wins) else 0.0,
            "avg_loss": float(losses.mean()) if len(losses) else 0.0,
            "exp": float(pnl.mean()), "pf": float(wins.sum() / gl) if gl > 0 else float("inf"),
            "total": float(pnl.sum()), "maxdd": float((np.maximum.accumulate(equity) - equity).max())}


def verdict(m, n_days):
    """Gates from the backtest-expert method, in order."""
    if m["n"] < 30:
        return f"NOT EVALUABLE: only {m['n']} trades (need 30 minimum, 100+ preferred)."
    if m["exp"] <= 0:
        return "REJECT: expectancy is zero or negative after costs and slippage."
    if m["maxdd"] >= CAPITAL * 0.5:
        return "REJECT: max drawdown is 50%+ of capital."
    return (f"VALIDATION REQUIRED: positive on {n_days} days, but the test period is far under the 5 years "
            "needed. Not enough evidence to risk real money.")


def fmt(m):
    pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
    return (f"{m['n']} trades | win {m['win']:.0f}% | avg win Rs {m['avg_win']:.2f} | avg loss Rs {m['avg_loss']:.2f} "
            f"| expectancy Rs {m['exp']:.2f}/trade | profit factor {pf} | total Rs {m['total']:.2f} | max drawdown Rs {m['maxdd']:.2f}")


def _clean(m):
    """JSON-safe copy of a metrics dict (no inf / numpy types)."""
    return {k: (None if isinstance(v, float) and v in (float("inf"), float("-inf")) else float(v)) for k, v in m.items()}


def save_result(result, text):
    """Store the run in Supabase so the dashboard's Backtest tab can show it (skipped if no keys)."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("[info] SUPABASE_URL/KEY not set, results not saved to the dashboard.")
        return
    try:
        from supabase import create_client
        create_client(url, key).table("backtest_runs").insert({"result": result, "summary_md": text}).execute()
        print("[info] Saved to Supabase: open the dashboard's Backtest tab.")
    except Exception as e:  # never fail the run because of the save
        print(f"[warn] Could not save results: {e}")


def _write_summary(text):
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text + "\n")


def _prepare(data):
    data = data if data is not None else load_data(SYMBOLS)
    if not data:
        print("No data downloaded, nothing to test.")
        return None, None
    days = sorted({d for df in data.values() for d in df.index.date})
    if len(days) < 10:
        print(f"Only {len(days)} days of data, too few to test.")
        return None, None
    return data, days


def main(data=None):
    data, days = _prepare(data)
    if data is None:
        return ""
    cut = int(len(days) * TRAIN_FRACTION)
    train_days, test_days = days[:cut], days[cut:]

    grid = {(s, r): simulate(data, days, s, r) for s, r in itertools.product(STOPS, RRS)}
    gm = {k: metrics(v) for k, v in grid.items()}
    base = gm[BASE]

    out = ["# ORB backtest", "",
           f"Stocks: {', '.join(data)} | {len(days)} trading days ({days[0]} to {days[-1]}) | capital Rs {CAPITAL:.0f}",
           f"Costs: {COST_PCT}% round trip + {SLIPPAGE_PCT}% slippage per side. Sizing, cash limit, max trades and loss cap as in the bot.", "",
           f"## Baseline (stop {BASE[0]}%, target {BASE[1]}x risk)", fmt(base), "",
           f"**Verdict:** {verdict(base, len(days))}", "",
           "## Total net P&L in Rs by setting (rows = stop %, columns = target multiple)",
           "| stop % | " + " | ".join(f"{r}x" for r in RRS) + " |", "|---|" + "---|" * len(RRS)]
    for s in STOPS:
        out.append(f"| {s} | " + " | ".join(f"{gm[(s, r)]['total']:.0f}" for r in RRS) + " |")
    positive = sum(1 for m in gm.values() if m["total"] > 0)
    out += ["", f"Profitable settings: {positive} of {len(gm)}. A real edge shows a broad plateau of positive cells; "
            "one or two isolated positive cells usually mean curve-fitting.", ""]

    # Walk-forward style check: pick the best settings on training days, judge them on unseen test days.
    best = max(grid, key=lambda k: metrics([t for t in grid[k] if t["day"] in set(train_days)])["total"])
    tr = metrics([t for t in grid[best] if t["day"] in set(train_days)])
    te = metrics([t for t in grid[best] if t["day"] in set(test_days)])
    out += [f"## Train vs test (best settings on training days: stop {best[0]}%, target {best[1]}x)",
            f"Train ({len(train_days)} days): {fmt(tr)}", f"Test ({len(test_days)} unseen days): {fmt(te)}", ""]
    overfit = bool(te["n"] and tr["exp"] > 0 and te["exp"] < 0.5 * tr["exp"])
    if overfit:
        out.append("Warning: out-of-sample expectancy is under half of in-sample. Typical sign of overfitting.")
    out += ["", "Limits: free 5-minute data covers about 60 days, entries assume the bar close, stops assume a fill at the "
            "stop price, and results are paper only. This is a smoke test, not proof of an edge. Not financial advice."]
    text = "\n".join(out)
    print(text)
    result = {
        "meta": {"symbols": list(data), "days": len(days), "first": str(days[0]), "last": str(days[-1]),
                 "capital": CAPITAL, "cost_pct": COST_PCT, "slippage_pct": SLIPPAGE_PCT},
        "baseline": {**_clean(base), "stop": BASE[0], "rr": BASE[1], "verdict": verdict(base, len(days))},
        "grid": [{"stop": s, "rr": r, **_clean(gm[(s, r)])} for s, r in itertools.product(STOPS, RRS)],
        "positive": positive, "cells": len(gm),
        "best": {"stop": best[0], "rr": best[1]},
        "train": {**_clean(tr), "days": len(train_days)}, "test": {**_clean(te), "days": len(test_days)},
        "overfit_warning": overfit,
    }
    save_result(result, text)
    _write_summary(text)
    return text


def lab_verdict(tr, te):
    if tr["n"] == 0 or te["n"] == 0:
        return "NO TRADES"
    if tr["exp"] <= 0:
        return "NEGATIVE EVEN IN TRAINING"
    if te["exp"] <= 0:
        return "FAILS ON UNSEEN DAYS"
    if te["n"] < 30:
        return "PROMISING BUT TOO FEW TRADES"
    return "PASSES (confirm on fresh data)"


def lab(data=None):
    data, days = _prepare(data)
    if data is None:
        return ""
    cut = int(len(days) * TRAIN_FRACTION)
    train_days, test_days = set(days[:cut]), set(days[cut:])

    # Is there any edge before costs? Baseline rules, zero costs and zero slippage.
    gross = metrics(simulate(data, days, *BASE, opts={"slip_pct": 0.0}, cost_pct=0.0))
    with_costs = metrics(simulate(data, days, *BASE))

    rows = []
    for name, opts in VARIANTS:
        grid = {(s, r): simulate(data, days, s, r, opts) for s, r in itertools.product(STOPS, RRS)}
        best = max(grid, key=lambda k: metrics([t for t in grid[k] if t["day"] in train_days])["total"])
        tr = metrics([t for t in grid[best] if t["day"] in train_days])
        te = metrics([t for t in grid[best] if t["day"] in test_days])
        positive = sum(1 for k in grid if metrics(grid[k])["total"] > 0)
        rows.append({"name": name, "best": {"stop": best[0], "rr": best[1]}, "positive": positive, "cells": len(grid),
                     "train": {**_clean(tr), "days": len(train_days)}, "test": {**_clean(te), "days": len(test_days)},
                     "verdict": lab_verdict(tr, te)})

    out = ["# ORB strategy lab", "",
           f"Stocks: {', '.join(data)} | {len(days)} days ({days[0]} to {days[-1]}) | train {len(train_days)} days, test {len(test_days)} unseen days",
           f"Costs: {COST_PCT}% round trip + {SLIPPAGE_PCT}% slippage per side (unless stated).", "",
           "## Is there any edge before costs? (baseline rules)",
           f"No costs, no slippage: {fmt(gross)}", f"With costs and slippage: {fmt(with_costs)}", "",
           "## Variants (best stop/target picked on training days, then judged on unseen days)",
           "| Variant | Best setting | Train Rs | Test Rs | Test trades | Profitable cells | Result |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['name']} | {r['best']['stop']}% / {r['best']['rr']}x | {r['train']['total']:.0f} | {r['test']['total']:.0f} "
                   f"| {r['test']['n']:.0f} | {r['positive']}/{r['cells']} | {r['verdict']} |")
    tried = len(VARIANTS) * len(STOPS) * len(RRS)
    out += ["", f"Warning: {tried} combinations were tried on the same {len(days)} days. With that many tries, some will look good "
            "by luck. Treat any PASS as a lead to confirm with fresh paper trading, not as proof. Do not run more rounds of "
            "variants on this same data.", "", "Not financial advice."]
    text = "\n".join(out)
    print(text)
    result = {"kind": "lab",
              "meta": {"symbols": list(data), "days": len(days), "first": str(days[0]), "last": str(days[-1]), "capital": CAPITAL,
                       "cost_pct": COST_PCT, "slippage_pct": SLIPPAGE_PCT, "tried": tried},
              "gross": _clean(gross), "with_costs": _clean(with_costs), "variants": rows}
    save_result(result, text)
    _write_summary(text)
    return text


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "lab":
        lab()
    else:
        main()
