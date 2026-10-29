"""
Optional Angel One SmartAPI historical-candle fetcher. NOT used by the trading bot (the bot uses Yahoo).

Why this exists: Angel One's getCandleData often answers "Access denied because of exceeding access rate",
even at low request rates. Their limit is 3/sec, 120/min and 5000/hour PER CLIENT CODE. So this module:
  * keeps at least MIN_GAP seconds between calls,
  * on that error waits a long time (minutes, not seconds) and gives up after a few tries,
  * stops completely after giving up (AngelBlocked) instead of hammering the endpoint,
  * caches every successful answer on disk so the same request is never sent twice,
  * splits long date ranges to the per-interval maximum,
  * never prints keys, PINs, TOTP secrets or tokens.

Environment variables (put them in .env on the server or in secrets; never in code):
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
"""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta

MIN_GAP = 2.5                       # seconds between calls (limit is 3/sec; stay far below)
BACKOFFS = (120, 300, 600)          # waits after a block: 2 min, 5 min, 10 min. Then stop.
CACHE_DIR = os.getenv("ANGEL_CACHE_DIR", ".angel_cache")
MAX_DAYS = {"ONE_MINUTE": 30, "THREE_MINUTE": 60, "FIVE_MINUTE": 100, "TEN_MINUTE": 100,
            "FIFTEEN_MINUTE": 200, "THIRTY_MINUTE": 200, "ONE_HOUR": 400, "ONE_DAY": 2000}
FMT = "%Y-%m-%d %H:%M"
BLOCK_WORDS = ("exceeding access rate", "exceeding rate limit", "access denied")


class AngelBlocked(RuntimeError):
    """Angel One kept refusing us. Stop and try again much later."""


class AngelError(RuntimeError):
    """Any other failure, with a message that is safe to print."""


def _is_block(msg):
    m = str(msg).lower()
    return any(w in m for w in BLOCK_WORDS)


def split_range(start, end, interval):
    """Cut [start, end] into windows no longer than the API allows for this interval."""
    days = MAX_DAYS[interval]
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        out.append((cur, nxt))
        cur = nxt
    return out


def parse_rows(rows):
    """[[ts, o, h, l, c, v], ...] -> list of dicts."""
    out = []
    for r in rows or []:
        out.append({"ts": r[0], "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])})
    return out


def _cache_path(exchange, token, interval, a, b):
    key = f"{exchange}|{token}|{interval}|{a.strftime(FMT)}|{b.strftime(FMT)}"
    return os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ".json")


class AngelClient:
    def __init__(self, api=None, sleep=time.sleep, clock=time.monotonic):
        self._api = api            # injectable for tests
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.calls = 0             # network calls actually sent (for your own awareness)

    def login(self):
        """Log in once. Prints nothing secret."""
        if self._api is not None:
            return
        need = ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"]
        missing = [n for n in need if not os.getenv(n)]
        if missing:
            raise AngelError("Missing environment variables: " + ", ".join(missing))
        try:
            import pyotp
            from SmartApi import SmartConnect
        except ImportError:
            raise AngelError("Install extras first: pip install -r requirements-angelone-test.txt")
        from angel_feed import silence_sdk_logging
        silence_sdk_logging()
        api = SmartConnect(api_key=os.environ["ANGEL_API_KEY"])
        totp = pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now()
        res = api.generateSession(os.environ["ANGEL_CLIENT_CODE"], os.environ["ANGEL_PIN"], totp)
        if not (isinstance(res, dict) and res.get("status")):
            msg = res.get("message") if isinstance(res, dict) else "unknown"
            raise AngelError(f"Login failed: {msg}")
        self._api = api

    def _pace(self):
        if self._last is not None:
            wait = MIN_GAP - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _fetch_window(self, exchange, token, interval, a, b):
        params = {"exchange": exchange, "symboltoken": str(token), "interval": interval,
                  "fromdate": a.strftime(FMT), "todate": b.strftime(FMT)}
        for attempt in range(len(BACKOFFS) + 1):
            self._pace()
            self.calls += 1
            try:
                res = self._api.getCandleData(params)
                if isinstance(res, dict) and res.get("status") is False:
                    raise AngelError(str(res.get("message") or res.get("errorcode") or "request refused"))
                return parse_rows((res or {}).get("data"))
            except Exception as e:        # the SDK raises DataException for the plain-text block page
                text = str(e)
                if not _is_block(text):
                    raise AngelError(f"{type(e).__name__}: {text[:150]}")
                if attempt >= len(BACKOFFS):
                    raise AngelBlocked(
                        "Angel One kept refusing (access rate). Stopped on purpose. "
                        "Try again in an hour or more, and make sure nothing else uses this client code.")
                self._sleep(BACKOFFS[attempt])
        raise AngelBlocked("unreachable")

    def candles(self, token, start, end, interval="FIVE_MINUTE", exchange="NSE", use_cache=True):
        """All candles between two datetimes (naive IST). Cached per window; stops on AngelBlocked."""
        if interval not in MAX_DAYS:
            raise AngelError(f"Unknown interval {interval}")
        os.makedirs(CACHE_DIR, exist_ok=True)
        out = []
        for a, b in split_range(start, end, interval):
            path = _cache_path(exchange, token, interval, a, b)
            if use_cache and os.path.exists(path):
                with open(path) as f:
                    out.extend(json.load(f))
                continue
            self.login()
            rows = self._fetch_window(exchange, token, interval, a, b)
            with open(path, "w") as f:
                json.dump(rows, f)
            out.extend(rows)
        return out


if __name__ == "__main__":
    # One careful request: yesterday-ish 09:15 to 09:45 for RELIANCE. Prints only a sanitized summary.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    end = datetime.now().replace(second=0, microsecond=0)
    day = end - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    start = day.replace(hour=9, minute=15)
    try:
        rows = AngelClient().candles("2885", start, start.replace(hour=9, minute=45), "ONE_MINUTE")
        print(f"OK: {len(rows)} candles" + (f", first {rows[0]['ts']}" if rows else ""))
    except AngelBlocked as e:
        print("BLOCKED:", e)
    except AngelError as e:
        print("ERROR:", e)
