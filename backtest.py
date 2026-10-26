"""
Backtest of the ORB (opening-range breakout) rules on free Yahoo 5-minute NSE data.

Follows the backtest-expert method: realistic costs + slippage, a parameter grid (look for a plateau,
not a spike), and a train/test split so the "best" settings are judged on days they never saw.

Yahoo only serves ~60 days of 5-minute history, so this is a SMOKE TEST, not proof of an edge.
Run it from the GitHub Actions tab: "backtest" -> Run workflow. Results appear in the run summary.
"""
import itertools
import os
import warnings
from datetime import time as dtime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
IST = ZoneInfo("Asia/Kolkata")

SYMBOLS = os.getenv("SYMBOLS", "RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS").split(",")
CAPITAL = float(os.getenv("CAPITAL", "4000"))
RISK_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
COST_PCT = float(os.getenv("COST_PCT", "0.10"))          # all-in round-trip cost, % of position value
SLIPPAGE_PCT = float(os.getenv("SLIPPAGE_PCT", "0.05"))  # per side, % of price
MAX_TRADES = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
DAILY_CAP_PCT = float(os.getenv("DAILY_LOSS_CAP_PCT", "3.0"))
TRAIN_FRACTION = 0.7

STOPS = [0.5, 0.75, 1.0, 1.25, 1.5]   # stop-loss % (baseline 1.0)
RRS = [1.0, 1.5, 2.0]                 # target as a multiple of risk (baseline 1.5)
BASE = (1.0, 1.5)

OPEN, RANGE_END, NO_NEW, SQUARE_OFF = dtime(9, 15), dtime(9, 30), dtime(14, 30), dtime(15, 15)
BAR = timedelta(minutes=5)


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
        out[s] = df[["Open", "High", "Low", "Close"]]
    return out


def _mask(index, lo, hi):
    return np.array([lo <= t < hi for t in index.time])


def find_signal(symbol, bars, stop_pct, rr):
    """First breakout of the day for one stock. Returns a trade dict (assuming it is taken) or None."""
    rng = bars[_mask(bars.index, OPEN, RANGE_END)]
    if len(rng) < 2:
        return None
    hi, lo = rng["High"].max(), rng["Low"].min()
    after = bars[_mask(bars.index, RANGE_END, SQUARE_OFF)]
    slip = SLIPPAGE_PCT / 100
    for i in range(len(after)):
        ts, row = after.index[i], after.iloc[i]
        if ts.time() >= NO_NEW:
            break
        close = float(row["Close"])
        side = 1 if close > hi else -1 if close < lo else 0
        if not side:
            continue
        entry = close * (1 + side * slip)
        stop = entry * (1 - side * stop_pct / 100)
        target = entry + side * abs(entry - stop) * rr
        exit_price, reason, exit_ts = None, "square_off", ts
        for j in range(i + 1, len(after)):
            r2, ts2 = after.iloc[j], after.index[j]
            exit_ts = ts2
            if side == 1:
                if r2["Low"] <= stop:
                    exit_price, reason = stop, "stop"
                    break
                if r2["High"] >= target:
                    exit_price, reason = target, "target"
                    break
            else:
                if r2["High"] >= stop:
                    exit_price, reason = stop, "stop"
                    break
                if r2["Low"] <= target:
                    exit_price, reason = target, "target"
                    break
        if exit_price is None:
            exit_price = float(after.iloc[-1]["Close"]) if len(after) > i + 1 else close
            exit_ts = after.index[-1] if len(after) > i + 1 else ts
        exit_fill = exit_price * (1 - side * slip)
        return {"symbol": symbol, "side": side, "entry": entry, "stop": stop, "exit_fill": exit_fill,
                "reason": reason, "entry_time": ts + BAR, "exit_time": exit_ts + BAR}
    return None


def run_day(signals):
    """Apply the bot's portfolio rules (cash limit, 1% risk sizing, max trades, daily loss cap)."""
    signals = sorted(signals, key=lambda s: s["entry_time"])
    cash, open_, trades, realized, taken = CAPITAL, [], [], 0.0, 0
    for s in signals:
        for o in [o for o in open_ if o["exit_time"] <= s["entry_time"]]:
            cash += o["value"] + o["gross"]
            realized += o["net"]
            open_.remove(o)
        if taken >= MAX_TRADES or realized <= -CAPITAL * DAILY_CAP_PCT / 100:
            break
        per_share = abs(s["entry"] - s["stop"])
        qty = min(int((CAPITAL * RISK_PCT / 100) // per_share), int(max(cash, 0) // s["entry"]))
        if qty < 1:
            continue
        value = qty * s["entry"]
        gross = (s["exit_fill"] - s["entry"]) * qty * s["side"]
        net = gross - COST_PCT / 100 * value
        cash -= value
        if cash < -1e-6:
            raise RuntimeError("cash went negative: sizing bug")
        taken += 1
        t = {"symbol": s["symbol"], "net": net, "gross": gross, "value": value,
             "exit_time": s["exit_time"], "reason": s["reason"], "side": s["side"]}
        open_.append(t)
        trades.append(t)
    return trades


def simulate(data, days, stop_pct, rr):
    trades = []
    for day in days:
        sigs = []
        for sym, df in data.items():
            bars = df[df.index.date == day]
            if bars.empty:
                continue
            sig = find_signal(sym, bars, stop_pct, rr)
            if sig:
                sigs.append(sig)
        for t in run_day(sigs):
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


def main(data=None):
    data = data if data is not None else load_data(SYMBOLS)
    if not data:
        print("No data downloaded, nothing to test.")
        return ""
    days = sorted({d for df in data.values() for d in df.index.date})
    if len(days) < 10:
        print(f"Only {len(days)} days of data, too few to test.")
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
    if te["n"] and tr["exp"] > 0 and te["exp"] < 0.5 * tr["exp"]:
        out.append("Warning: out-of-sample expectancy is under half of in-sample. Typical sign of overfitting.")
    out += ["", "Limits: free 5-minute data covers about 60 days, entries assume the bar close, stops assume a fill at the "
            "stop price, and results are paper only. This is a smoke test, not proof of an edge. Not financial advice."]
    text = "\n".join(out)
    print(text)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text + "\n")
    return text


if __name__ == "__main__":
    main()
