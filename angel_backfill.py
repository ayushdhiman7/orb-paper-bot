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


def _parse(row, now):
    """Return a completed 5m candle dict for today, or None."""
    stamp = datetime.fromisoformat(str(row[0]))
    stamp = stamp.replace(tzinfo=IST) if stamp.tzinfo is None else stamp.astimezone(IST)
    if stamp.date() != now.date() or stamp + timedelta(minutes=5) > now:
        return None
    o, h, l, c, v = (float(x) for x in row[1:6])
    if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)) or not math.isfinite(v) or v < 0:
        return None
    return {"timestamp": stamp, "open": o, "high": h, "low": l, "close": c, "volume": v}


def fetch_today_candles(api, token, now, *, sleep=time.sleep, pause=0.4, attempts=3):
    params = {
        "exchange": "NSE", "symboltoken": str(token), "interval": "FIVE_MINUTE",
        "fromdate": now.strftime("%Y-%m-%d ") + "09:15", "todate": now.strftime("%Y-%m-%d %H:%M"),
    }
    for attempt in range(attempts):
        try:
            response = api.getCandleData(params)
            if isinstance(response, dict) and response.get("status") and isinstance(response.get("data"), list):
                rows = [c for c in (_parse(r, now) for r in response["data"]) if c]
                return sorted(rows, key=lambda r: r["timestamp"])
        except Exception:
            pass
        sleep(pause * (2 ** attempt))
    return None


def backfill_today(feed, api, universe, now, *, sleep=time.sleep, pause=0.4):
    """Seed today's completed bars for every symbol. Returns (seeded, failed) symbol lists."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(IST)
    if (now.hour, now.minute) < (9, 20):
        return [], []   # no completed bar exists yet
    seeded, failed = [], []
    for row in universe:
        rows = fetch_today_candles(api, row["token"], now, sleep=sleep, pause=pause)
        if rows is None:
            failed.append(row["symbol"])
        else:
            feed.seed_completed(row["symbol"], rows, now.date())
            seeded.append(row["symbol"])
        sleep(pause)   # stay under Angel's historical-data rate limit
    return seeded, failed
