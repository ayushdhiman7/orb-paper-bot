"""Offline tests for angel_data.py (no network, no credentials). Run: python test_angel_data.py"""
import os
import shutil
import tempfile
from datetime import datetime

os.environ["ANGEL_CACHE_DIR"] = tempfile.mkdtemp()
import angel_data as ad  # noqa: E402

ad.CACHE_DIR = os.environ["ANGEL_CACHE_DIR"]


class FakeApi:
    def __init__(self, script):
        self.script, self.n = list(script), 0

    def getCandleData(self, params):
        self.n += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


ROW = ["2026-10-26T09:15:00+05:30", 100, 101, 99, 100.5, 1000]
OK = {"status": True, "data": [ROW]}
BLOCK = Exception("Couldn't parse the JSON response: b'Access denied because of exceeding access rate'")
t0 = datetime(2026, 10, 26, 9, 15)
t1 = datetime(2026, 10, 26, 9, 45)


def client(script):
    sleeps = []
    api = FakeApi(script)
    return ad.AngelClient(api=api, sleep=sleeps.append, clock=lambda: 0.0), api, sleeps


# 1. splitting respects per-interval maximum
w = ad.split_range(datetime(2026, 1, 1), datetime(2026, 3, 15), "ONE_MINUTE")
assert len(w) == 3 and all((b - a).days <= 30 for a, b in w), w
assert ad.split_range(t0, t1, "FIVE_MINUTE") == [(t0, t1)]

# 2. success, parsing and caching (second call sends nothing)
c, api, s = client([OK])
r = c.candles("2885", t0, t1, "ONE_MINUTE")
assert r == [{"ts": ROW[0], "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}]
c2, api2, _ = client([])
assert c2.candles("2885", t0, t1, "ONE_MINUTE") == r and api2.n == 0

# 3. block then success: waits 120s once, then returns
shutil.rmtree(ad.CACHE_DIR); os.makedirs(ad.CACHE_DIR)
c, api, s = client([BLOCK, OK])
assert len(c.candles("2885", t0, t1, "ONE_MINUTE")) == 1
assert api.n == 2 and 120 in s, (api.n, s)

# 4. always blocked: exactly 4 attempts, long waits, then AngelBlocked (no hammering)
shutil.rmtree(ad.CACHE_DIR); os.makedirs(ad.CACHE_DIR)
c, api, s = client([BLOCK] * 10)
try:
    c.candles("2885", t0, t1, "ONE_MINUTE")
    raise SystemExit("should have raised")
except ad.AngelBlocked:
    pass
assert api.n == 4 and [x for x in s if x >= 120] == [120, 300, 600], (api.n, s)

# 5. other errors fail fast, no retry, and are not mistaken for a block
shutil.rmtree(ad.CACHE_DIR); os.makedirs(ad.CACHE_DIR)
c, api, s = client([Exception("Invalid Token")])
try:
    c.candles("2885", t0, t1, "ONE_MINUTE")
    raise SystemExit("should have raised")
except ad.AngelError as e:
    assert "Invalid Token" in str(e) and api.n == 1

# 6. pacing: second call in the same client waits MIN_GAP (clock frozen at 0)
shutil.rmtree(ad.CACHE_DIR); os.makedirs(ad.CACHE_DIR)
c, api, s = client([OK, OK])
c.candles("2885", t0, t1, "ONE_MINUTE")
c.candles("2885", datetime(2026, 10, 23, 9, 15), datetime(2026, 10, 23, 9, 45), "ONE_MINUTE")
assert ad.MIN_GAP in s, s

# 7. missing credentials give a clear, secret-free message
for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
    os.environ.pop(k, None)
try:
    ad.AngelClient().login()
except ad.AngelError as e:
    assert "ANGEL_API_KEY" in str(e)

shutil.rmtree(ad.CACHE_DIR, ignore_errors=True)
print("ALL ANGEL TESTS PASSED")
