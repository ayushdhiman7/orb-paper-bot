"""
Opening-Range-Breakout PAPER trading bot for NSE stocks.

- Data: yfinance (free, ~15 min delayed for NSE, fine for paper testing).
- Orders: simulated only. No broker connection, no real money.
- Logging: Supabase (optional). Falls back to local CSV if keys are missing.
"""
import csv
import os
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import yfinance as yf

import llm_gate

warnings.filterwarnings("ignore")  # yfinance/pandas deprecation noise buries the real log lines

IST = ZoneInfo("Asia/Kolkata")

# ---------------- Config (override with environment variables) ----------------
SYMBOLS = os.getenv("SYMBOLS", "RELIANCE.NS,TCS.NS,INFY.NS,HDFCBANK.NS,ICICIBANK.NS").split(",")
CAPITAL = float(os.getenv("CAPITAL", "4000"))          # INR, paper money
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "1.0"))
TARGET_RR = float(os.getenv("TARGET_RR", "1.5"))       # take profit = 1.5x risk
DAILY_LOSS_CAP_PCT = float(os.getenv("DAILY_LOSS_CAP_PCT", "3.0"))
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
COST_PER_ORDER = float(os.getenv("COST_PER_ORDER", "20"))  # rough brokerage+charges, INR
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
ONE_DAY = os.getenv("ONE_DAY", "0") == "1"   # exit after today's session (used by GitHub Actions)
# AI second opinion (Gemini). "off" = never ask, "shadow" = ask and record the answer but trade anyway (default),
# "gate" = skip trades the AI votes against. Needs the GEMINI_API_KEY secret; without it nothing changes.
LLM_MODE = os.getenv("LLM_MODE", "shadow").lower()

MARKET_OPEN = dtime(9, 15)
RANGE_END = dtime(9, 30)      # opening range = 9:15 to 9:30
NO_NEW_TRADES_AFTER = dtime(14, 30)
SQUARE_OFF = dtime(15, 15)
MARKET_CLOSE = dtime(15, 30)


@dataclass
class Position:
    symbol: str
    side: str        # "BUY" or "SELL"
    qty: int
    entry: float
    stop: float
    target: float
    opened_at: datetime
    row_id: object = None    # Supabase row id of this trade while it is open
    llm_decision: str = None  # AI second opinion: "take" or "skip" (None if not asked)
    llm_reason: str = None


@dataclass
class State:
    cash: float = CAPITAL
    day_pnl: float = 0.0
    trades_today: int = 0
    ranges: dict = field(default_factory=dict)
    positions: dict = field(default_factory=dict)
    done_symbols: set = field(default_factory=set)
    halted: bool = False


# ---------------- Logging ----------------
def get_supabase():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    from supabase import create_client
    return create_client(url, key)


SB = get_supabase()


def log_entry(pos):
    """Save a trade as 'open' the moment it is entered, so the dashboard can show it."""
    if not SB:
        return None
    try:
        res = SB.table("paper_trades").insert({
            "ts": pos.opened_at.isoformat(), "symbol": pos.symbol, "side": pos.side,
            "qty": pos.qty, "entry": round(pos.entry, 2), "reason": "open",
            "last_price": round(pos.entry, 2), "last_price_ts": pos.opened_at.isoformat(),
            **({"llm_decision": pos.llm_decision, "llm_reason": pos.llm_reason} if pos.llm_decision else {}),
            "status": "open", "mode": "paper",
        }).execute()
        return res.data[0]["id"]
    except Exception as e:  # never let logging crash the bot
        print(f"[warn] Supabase open-trade insert failed: {e}")
        return None


def log_price(pos, price: float, now):
    """Save the latest price of an open trade so the dashboard can show live unrealised P&L."""
    if not SB or pos.row_id is None:
        return
    try:
        SB.table("paper_trades").update(
            {"last_price": round(price, 2), "last_price_ts": now.isoformat()}
        ).eq("id", pos.row_id).execute()
    except Exception as e:  # never let logging crash the bot
        print(f"[warn] Supabase price update failed: {e}")


def log_trade(row: dict, row_id=None):
    if SB:
        try:
            if row_id is not None:
                SB.table("paper_trades").update({**row, "status": "closed"}).eq("id", row_id).execute()
            else:
                SB.table("paper_trades").insert({**row, "status": "closed"}).execute()
            return
        except Exception as e:  # never let logging crash the bot
            print(f"[warn] Supabase write failed: {e}")
    new = not os.path.exists("trades.csv")
    with open("trades.csv", "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


# ---------------- Data ----------------
def fetch_candles(symbol: str):
    """1-minute candles for today. Returns a DataFrame indexed in IST."""
    df = yf.Ticker(symbol).history(period="1d", interval="1m")
    if df.empty:
        return df
    df.index = df.index.tz_convert(IST)
    return df


def last_price(symbol: str):
    df = fetch_candles(symbol)
    return None if df.empty else float(df["Close"].iloc[-1])


# ---------------- Strategy ----------------
def compute_opening_range(symbol: str):
    df = fetch_candles(symbol)
    if df.empty:
        return None
    # Data is delayed ~15 min: wait until the candles cover the whole 9:15-9:30 window.
    if df.index.max().time() < dtime(9, 29):
        return None
    window = df.between_time(MARKET_OPEN, RANGE_END)
    if window.empty:
        return None
    return float(window["High"].max()), float(window["Low"].min())


def size_position(price: float, stop: float, cash: float = None) -> int:
    risk_cash = CAPITAL * RISK_PER_TRADE_PCT / 100
    per_share_risk = abs(price - stop)
    if per_share_risk <= 0:
        return 0
    qty_by_risk = int(risk_cash // per_share_risk)
    available = CAPITAL if cash is None else cash   # cash NOT already tied up in open positions
    qty_by_cash = int(max(0.0, available) // price)  # no leverage, keeps it honest
    return max(0, min(qty_by_risk, qty_by_cash))


def ask_ai(symbol, side, price, stop, target, rng, now):
    """Small fact sheet about this breakout, sent to the AI for a take/skip opinion. Never raises."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return None   # no key set: do nothing, no extra data fetch
    try:
        df = fetch_candles(symbol)
        ctx = {"symbol": symbol, "side": side, "time_ist": f"{now:%H:%M}", "entry_price": round(price, 2),
               "stop": round(stop, 2), "target": round(target, 2),
               "opening_range_high": round(rng[0], 2), "opening_range_low": round(rng[1], 2),
               "opening_range_width_pct": round((rng[0] - rng[1]) / rng[1] * 100, 2)}
        if not df.empty:
            day_open = float(df["Open"].iloc[0])
            ctx["day_open"] = round(day_open, 2)
            ctx["move_since_open_pct"] = round((price - day_open) / day_open * 100, 2)
            ctx["last_12_five_min_closes"] = [round(float(x), 2) for x in df["Close"].resample("5min").last().dropna().tail(12)]
            if "Volume" in df.columns and float(df["Volume"].mean()) > 0:
                ctx["volume_last_5min_vs_day_average"] = round(float(df["Volume"].tail(5).mean() / df["Volume"].mean()), 2)
        return llm_gate.review(ctx)
    except Exception as e:  # the AI is optional: never let it break trading
        print(f"[warn] AI review skipped: {type(e).__name__}")
        return None


def try_entry(state: State, symbol: str, now: datetime):
    if symbol in state.positions or symbol in state.done_symbols:
        return
    if state.trades_today >= MAX_TRADES_PER_DAY or state.halted:
        return
    rng = state.ranges.get(symbol)
    price = last_price(symbol)
    if not rng or price is None:
        return
    high, low = rng
    side = None
    if price > high:
        side, stop = "BUY", price * (1 - STOP_LOSS_PCT / 100)
    elif price < low:
        side, stop = "SELL", price * (1 + STOP_LOSS_PCT / 100)
    if not side:
        return
    qty = size_position(price, stop, state.cash)
    if qty < 1:
        print(f"[skip] {symbol}: price {price:.2f} too high for capital/risk")
        state.done_symbols.add(symbol)
        return
    risk = abs(price - stop)
    target = price + risk * TARGET_RR if side == "BUY" else price - risk * TARGET_RR
    review = ask_ai(symbol, side, price, stop, target, rng, now) if LLM_MODE in ("shadow", "gate") else None
    if review:
        print(f"[AI] {symbol} {side}: {review['decision']} - {review['reason']}")
        if LLM_MODE == "gate" and review["decision"] == "skip":
            print(f"[skip] {symbol}: AI advised skipping")
            state.done_symbols.add(symbol)
            return
    pos = Position(symbol, side, qty, price, stop, target, now)
    if review:
        pos.llm_decision, pos.llm_reason = review["decision"], review["reason"]
    pos.row_id = log_entry(pos)
    state.positions[symbol] = pos
    state.cash -= qty * price
    state.trades_today += 1
    state.day_pnl -= COST_PER_ORDER
    print(f"[ENTRY] {side} {qty} {symbol} @ {price:.2f} SL {stop:.2f} TP {target:.2f}")


def close_position(state: State, symbol: str, price: float, reason: str, now: datetime):
    pos = state.positions.pop(symbol)
    direction = 1 if pos.side == "BUY" else -1
    pnl = (price - pos.entry) * pos.qty * direction - COST_PER_ORDER
    state.day_pnl += pnl
    state.cash += pos.qty * pos.entry + (price - pos.entry) * pos.qty * direction  # free the cash
    state.done_symbols.add(symbol)
    print(f"[EXIT] {symbol} @ {price:.2f} ({reason}) net PnL {pnl:+.2f}")
    log_trade({
        "ts": now.isoformat(), "symbol": symbol, "side": pos.side, "qty": pos.qty,
        "entry": round(pos.entry, 2), "exit": round(price, 2),
        "pnl": round(pnl, 2), "reason": reason, "mode": "paper",
    }, row_id=pos.row_id)


def manage_positions(state: State, now: datetime):
    for symbol in list(state.positions):
        pos = state.positions[symbol]
        price = last_price(symbol)
        if price is None:
            continue
        log_price(pos, price, now)
        hit_stop = price <= pos.stop if pos.side == "BUY" else price >= pos.stop
        hit_target = price >= pos.target if pos.side == "BUY" else price <= pos.target
        if hit_stop:
            close_position(state, symbol, price, "stop_loss", now)
        elif hit_target:
            close_position(state, symbol, price, "target", now)


def check_daily_cap(state: State):
    if state.day_pnl <= -CAPITAL * DAILY_LOSS_CAP_PCT / 100 and not state.halted:
        state.halted = True
        print(f"[HALT] Daily loss cap hit ({state.day_pnl:.2f}). No new trades today.")


# ---------------- Main loop ----------------
def run():
    state = State()
    print(f"Paper bot started | capital Rs {CAPITAL} | symbols {SYMBOLS}")
    while True:
        now = datetime.now(IST)
        t = now.time()

        if ONE_DAY and (now.weekday() >= 5 or t > MARKET_CLOSE):
            print(f"Day summary: trades {state.trades_today}, net PnL {state.day_pnl:+.2f}")
            return

        if now.weekday() >= 5 or t < MARKET_OPEN or t > MARKET_CLOSE:
            print(f"{now:%H:%M} market closed, sleeping")
            if t > MARKET_CLOSE and state.trades_today:
                print(f"Day summary: trades {state.trades_today}, net PnL {state.day_pnl:+.2f}")
                state = State()  # reset for next day
            time.sleep(300)
            continue

        if t >= SQUARE_OFF:
            for sym in list(state.positions):
                p = last_price(sym)
                if p is not None:
                    close_position(state, sym, p, "square_off", now)
            if ONE_DAY:
                print(f"Day summary: trades {state.trades_today}, net PnL {state.day_pnl:+.2f}")
                return
        elif t >= RANGE_END:
            if not state.ranges:
                for sym in SYMBOLS:
                    r = compute_opening_range(sym)
                    if r:
                        state.ranges[sym] = r
                        print(f"[RANGE] {sym}: high {r[0]:.2f} low {r[1]:.2f}")
            manage_positions(state, now)
            check_daily_cap(state)
            if t < NO_NEW_TRADES_AFTER:
                for sym in SYMBOLS:
                    try_entry(state, sym, now)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
