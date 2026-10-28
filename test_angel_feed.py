"""Offline tests for angel_feed.py and its use in bot.py (no network, no credentials). Run: python test_angel_feed.py"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import angel_feed as af
import bot

IST = ZoneInfo("Asia/Kolkata")
D = datetime(2026, 10, 28, tzinfo=IST)
at = lambda h, m, s=0: D.replace(hour=h, minute=m, second=s)


class FakeApi:
    def __init__(self):
        self.prices = {"2885": 1170.0, "11536": 2440.0, "1594": 1150.0, "1333": 680.0, "4963": 1380.0}
        self.names = {"2885": "RELIANCE-EQ", "11536": "TCS-EQ", "1594": "INFY-EQ", "1333": "HDFCBANK-EQ", "4963": "ICICIBANK-EQ"}
        self.fail = False
        self.calls = 0
        self.last_req = None

    def getMarketData(self, mode, tokens):
        self.calls += 1
        self.last_req = (mode, tokens)
        if self.fail:
            raise Exception("Access denied because of exceeding access rate")
        return {"status": True, "data": {"fetched": [
            {"exchange": "NSE", "tradingSymbol": self.names[t], "symbolToken": t, "ltp": self.prices[t]}
            for t in tokens["NSE"]], "unfetched": []}}


SYMS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]

# 1) one call for all stocks, ticks recorded, fresh price returned
api = FakeApi(); f = af.AngelFeed(SYMS, api=api)
assert f.poll(at(9, 20)) == 5 and api.calls == 1 and api.last_req[0] == "LTP"
assert sorted(api.last_req[1]["NSE"]) == sorted(af.TOKENS.values())
assert f.last("RELIANCE.NS", at(9, 20, 10)) == 1170.0
print("one call for all stocks OK")

# 2) stale price is not live
assert f.last("RELIANCE.NS", at(9, 22)) is None; print("stale -> None OK")

# 3) opening range from samples every 5s 9:15-9:30
api = FakeApi(); f = af.AngelFeed(SYMS, api=api)
t = at(9, 15, 0); i = 0
while t <= at(9, 30):
    api.prices["2885"] = 1170 + (i % 10) - 4        # 1166 .. 1175
    f.poll(t); t += timedelta(seconds=5); i += 1
hi, lo = f.opening_range("RELIANCE.NS"); assert (hi, lo) == (1175.0, 1166.0), (hi, lo)
print("opening range from live samples OK", hi, lo)

# 4) started late (first sample 9:25): range refused, so the bot falls back to Yahoo
f2 = af.AngelFeed(SYMS, api=FakeApi()); t = at(9, 25)
while t <= at(9, 30):
    f2.poll(t); t += timedelta(seconds=5)
assert f2.opening_range("RELIANCE.NS") is None; print("late start -> None OK")

# 5) rate-limit errors: no crash, returns 0, pauses after repeated failures, recovers after pause
api = FakeApi(); f = af.AngelFeed(SYMS, api=api); api.fail = True; t = at(10, 0)
for _ in range(5):
    assert f.poll(t) == 0; t += timedelta(seconds=5)
assert f.paused_until is not None; calls = api.calls
assert f.poll(t) == 0 and api.calls == calls            # paused: no call sent
api.fail = False; assert f.poll(t + timedelta(seconds=af.PAUSE_SECONDS + 1)) == 5
print("failure pause + recovery OK")

# 6) a token that comes back under the wrong name is distrusted
api = FakeApi(); api.names["1333"] = "SOMETHINGELSE-EQ"; f = af.AngelFeed(SYMS, api=api)
f.poll(at(11, 0)); assert "HDFCBANK" in f.bad and f.last("HDFCBANK.NS", at(11, 0)) is None
assert f.last("TCS.NS", at(11, 0)) == 2440.0
f.poll(at(11, 0, 5)); assert "1333" not in api.last_req[1]["NSE"]; print("wrong token distrusted OK")

# 7) missing credentials: login() is False with a secret-free message
for names in af.NAMES.values():
    for n in names:
        os.environ.pop(n, None)
f = af.AngelFeed(SYMS); assert f.login() is False and "missing credentials" in f.last_error; print("missing creds OK")

# 8) bot integration: feed wins; no fresh feed price -> Yahoo; range from feed else Yahoo
yahoo_df = pd.DataFrame({"Open": [1.0], "High": [1200.0], "Low": [1100.0], "Close": [1111.0]},
                        index=pd.DatetimeIndex([at(9, 29)]))
bot.fetch_candles = lambda s: yahoo_df
api = FakeApi(); feed = af.AngelFeed(SYMS, api=api)
t = at(9, 15)
while t <= at(9, 30):
    feed.poll(t); t += timedelta(seconds=5)
bot.FEED = feed
real_now = bot.datetime
class FakeDT(real_now):
    @classmethod
    def now(cls, tz=None): return at(9, 30, 10)
bot.datetime = FakeDT
assert bot.last_price("RELIANCE.NS") == 1170.0
assert bot.compute_opening_range("RELIANCE.NS") == (1170.0, 1170.0)
class LaterDT(real_now):
    @classmethod
    def now(cls, tz=None): return at(9, 40)
bot.datetime = LaterDT
assert bot.last_price("RELIANCE.NS") == 1111.0           # feed price stale -> Yahoo fallback
bot.FEED = None
assert bot.last_price("RELIANCE.NS") == 1111.0
assert bot.compute_opening_range("RELIANCE.NS") == (1200.0, 1100.0)   # pure Yahoo as before
bot.datetime = real_now
print("bot integration OK")
print("ALL ANGEL FEED TESTS PASSED")
