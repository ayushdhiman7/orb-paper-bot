"""
Live price feed from Angel One SmartAPI (market quote / LTP). Used by bot.py when DATA_SOURCE=angel.

Why: Yahoo prices are ~15 minutes late. Angel One's live quote call works even though its historical-candle call
is often blocked, so this feed asks for the live price of every stock in ONE call every few seconds and builds
what the bot needs from those samples (latest price, and the 9:15-9:30 opening range).

Fail-safe: any problem (login, missing packages, rate block, odd data) makes the feed report "no data", and the
bot falls back to Yahoo for that moment. The feed never prints keys, PINs, TOTP secrets or tokens.

Environment variables (names are matched flexibly; values stay in .env):
  API key       ANGEL_API_KEY | SMARTAPI_API_KEY | API_KEY
  client code   ANGEL_CLIENT_CODE | ANGEL_CLIENT_ID | CLIENT_CODE | CLIENT_ID
  PIN           ANGEL_PIN | ANGEL_PASSWORD | PIN | PASSWORD
  TOTP secret   ANGEL_TOTP_SECRET | ANGEL_TOTP | TOTP_SECRET | TOTP_TOKEN
"""
import os
from datetime import time as dtime

# NSE equity tokens (Angel One scrip master). Names are re-checked against the quote reply at run time.
TOKENS = {"RELIANCE": "2885", "TCS": "11536", "INFY": "1594", "HDFCBANK": "1333", "ICICIBANK": "4963"}
NAMES = {
    "key": ("ANGEL_API_KEY", "SMARTAPI_API_KEY", "API_KEY"),
    "client": ("ANGEL_CLIENT_CODE", "ANGEL_CLIENT_ID", "CLIENT_CODE", "CLIENT_ID"),
    "pin": ("ANGEL_PIN", "ANGEL_PASSWORD", "PIN", "PASSWORD"),
    "totp": ("ANGEL_TOTP_SECRET", "ANGEL_TOTP", "TOTP_SECRET", "TOTP_TOKEN"),
}
MAX_STALE_SECONDS = 45        # a sample older than this is not "live" any more
MIN_RANGE_SAMPLES = 40        # samples needed inside 9:15-9:30 to trust the opening range
RANGE_START, RANGE_END = dtime(9, 15), dtime(9, 30)
MAX_FAILS_BEFORE_PAUSE = 5
PAUSE_SECONDS = 120


def _env(kind):
    for n in NAMES[kind]:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return ""


def silence_sdk_logging():
    """The SmartAPI SDK logs full request headers on any error, including the API key and the Bearer token.
    Keep those lines out of the logs (journald keeps them for weeks)."""
    import logging
    logging.getLogger("logzero_default").setLevel(logging.CRITICAL)
    try:
        from logzero import logger
        logger.setLevel(logging.CRITICAL)
    except Exception:
        pass


def base_name(symbol):
    return symbol.split(".")[0].upper()


class AngelFeed:
    def __init__(self, symbols, api=None, clock=None):
        self.symbols = [base_name(s) for s in symbols if base_name(s) in TOKENS]
        self._api = api                       # injectable for tests
        self._clock = clock                   # injectable: returns aware datetime
        self.ticks = {s: [] for s in self.symbols}   # name -> [(datetime, price)]
        self.fails = 0
        self.paused_until = None
        self.last_error = None
        self.bad = set()                      # symbols whose quote did not match the expected name

    # ---- login ----
    def login(self):
        """Returns True if logged in. Never raises, never prints secrets."""
        if self._api is not None:
            return True
        missing = [k for k in NAMES if not _env(k)]
        if missing:
            self.last_error = "missing credentials: " + ", ".join(missing)
            return False
        try:
            import pyotp
            from SmartApi import SmartConnect
        except ImportError:
            self.last_error = "smartapi-python / pyotp not installed"
            return False
        silence_sdk_logging()
        try:
            api = SmartConnect(api_key=_env("key"))
            res = api.generateSession(_env("client"), _env("pin"), pyotp.TOTP(_env("totp")).now())
        except Exception as e:
            self.last_error = f"login error: {type(e).__name__}"
            return False
        if not (isinstance(res, dict) and res.get("status")):
            self.last_error = "login refused: " + str((res or {}).get("message", "unknown"))[:80]
            return False
        self._api = api
        return True

    # ---- polling ----
    def _quotes(self):
        wanted = [s for s in self.symbols if s not in self.bad]
        tokens = [TOKENS[s] for s in wanted]
        res = self._api.getMarketData("LTP", {"NSE": tokens})
        if not (isinstance(res, dict) and res.get("status")):
            raise RuntimeError(str((res or {}).get("message", "refused"))[:80])
        out = {}
        for q in (res.get("data") or {}).get("fetched", []):
            sym = str(q.get("tradingSymbol", ""))
            name = next((s for s in wanted if sym.upper().startswith(s)), None)
            tok = str(q.get("symbolToken", ""))
            if name is None or (tok and tok != TOKENS[name]):
                continue
            ltp = q.get("ltp")
            if ltp:
                out[name] = float(ltp)
        # a token that came back under a different name is wrong: stop trusting it
        for q in (res.get("data") or {}).get("fetched", []):
            tok = str(q.get("symbolToken", ""))
            for s in wanted:
                if TOKENS[s] == tok and not str(q.get("tradingSymbol", "")).upper().startswith(s):
                    self.bad.add(s)
        return out

    def poll(self, now):
        """Take one sample of every stock. Returns number of stocks updated (0 on any problem)."""
        if self._api is None and not self.login():
            return 0
        if self.paused_until and now < self.paused_until:
            return 0
        try:
            quotes = self._quotes()
        except Exception as e:
            self.fails += 1
            self.last_error = f"quote error: {type(e).__name__} {str(e)[:60]}"
            if self.fails >= MAX_FAILS_BEFORE_PAUSE:
                from datetime import timedelta
                self.paused_until = now + timedelta(seconds=PAUSE_SECONDS)
                self.fails = 0
            return 0
        self.fails = 0
        for name, price in quotes.items():
            self.ticks[name].append((now, price))
        return len(quotes)

    # ---- what the bot asks for ----
    def last(self, symbol, now):
        """Latest price if it is fresh, else None (bot then falls back to Yahoo)."""
        t = self.ticks.get(base_name(symbol))
        if not t:
            return None
        ts, price = t[-1]
        return price if (now - ts).total_seconds() <= MAX_STALE_SECONDS else None

    def opening_range(self, symbol):
        """(high, low) from samples taken 9:15-9:30, or None if too few samples (e.g. bot started late)."""
        t = self.ticks.get(base_name(symbol), [])
        win = [p for ts, p in t if RANGE_START <= ts.time() <= RANGE_END]
        if len(win) < MIN_RANGE_SAMPLES:
            return None
        first = next(ts for ts, _ in t if ts.time() >= RANGE_START)
        if first.time() > dtime(9, 18):       # missed the start of the window: range would be too narrow
            return None
        return max(win), min(win)
