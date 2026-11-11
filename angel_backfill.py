"""Backfill today's completed 5-minute candles from Angel One history.

The WebSocket feed only sees ticks after it connects. Without this, a start after 09:15
(or a mid-day restart) has no opening range and the runner finds no candidates all day.
Read-only market data; fails soft per symbol (a missing symbol simply stays excluded).
"""
import math
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SESSION_START = (9, 15)


WARMUP_BARS = 40   # last bars of earlier sessions used only to seed the 20-bar EMA


def _parse(row, now, prior=False):
    """Return a completed 5m candle dict (today's, or an earlier session's when prior=True), or None."""
    stamp = datetime.fromisoformat(str(row[0]))
    stamp = stamp.replace(tzinfo=IST) if stamp.tzinfo is None else stamp.astimezone(IST)
    if prior:
        if stamp.date() >= now.date():
            return None
    elif stamp.date() != now.date() or stamp + timedelta(minutes=5) > now:
        return None
    o, h, l, c, v = (float(x) for x in row[1:6])
    if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)) or not math.isfinite(v) or v < 0:
        return None
    return {"timestamp": stamp, "open": o, "high": h, "low": l, "close": c, "volume": v}


def fetch_history(api, token, now, *, sleep=time.sleep, pause=0.4, attempts=3):
    """Return (today_bars, prior_session_bars) or None. One request covers both."""
    params = {
        "exchange": "NSE", "symboltoken": str(token), "interval": "FIVE_MINUTE",
        "fromdate": (now - timedelta(days=6)).strftime("%Y-%m-%d ") + "09:15",
        "todate": now.strftime("%Y-%m-%d %H:%M"),
    }
    for attempt in range(attempts):
        try:
            response = api.getCandleData(params)
            if isinstance(response, dict) and response.get("status") and isinstance(response.get("data"), list):
                data = response["data"]
                today = [c for c in (_parse(r, now) for r in data) if c]
                prior = [c for c in (_parse(r, now, prior=True) for r in data) if c]
                key = lambda r: r["timestamp"]
                return sorted(today, key=key), sorted(prior, key=key)[-WARMUP_BARS:]
        except Exception:
            pass
        sleep(pause * (2 ** attempt))
    return None


def fetch_today_candles(api, token, now, **kwargs):
    """Today's completed bars only (kept for callers that do not need warm-up bars)."""
    result = fetch_history(api, token, now, **kwargs)
    return None if result is None else result[0]


def backfill_today(feed, api, universe, now, *, sleep=time.sleep, pause=0.4):
    """Seed today's completed bars for every symbol. Returns (seeded, failed) symbol lists."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(IST)
    seeded, failed = [], []
    for row in universe:
        result = fetch_history(api, row["token"], now, sleep=sleep, pause=pause)
        if result is None:
            failed.append(row["symbol"])
        else:
            today, prior = result
            feed.seed_completed(row["symbol"], today, now.date())
            feed.set_warmup(row["symbol"], prior)
            seeded.append(row["symbol"])
        sleep(pause)   # stay under Angel's historical-data rate limit
    return seeded, failed
