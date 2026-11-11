from datetime import datetime
from zoneinfo import ZoneInfo

from angel_backfill import backfill_today, fetch_today_candles
from angel_websocket import AngelWebSocketFeed

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 11, 10, 18, 30, tzinfo=IST)


def bar(hh, mm, price):
    return [f"2026-11-11T{hh:02d}:{mm:02d}:00+05:30", price, price + 2, price - 2, price + 1, 1000]


class Api:
    def __init__(self, rows, fail_first=0):
        self.rows, self.calls, self.fail_first = rows, 0, fail_first

    def getCandleData(self, params):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("rate limited")
        return {"status": True, "data": self.rows}


def feed():
    return AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: 1000.0)


def test_backfill_gives_opening_range_and_survives_first_live_packet():
    f = feed()
    rows = [bar(9, 15, 2500), bar(9, 20, 2510), bar(9, 25, 2505), bar(10, 15, 2520)]  # 10:15 bar incomplete
    seeded, failed = backfill_today(f, Api(rows), [{"symbol": "RELIANCE", "token": "2885"}], NOW, sleep=lambda s: None)
    assert (seeded, failed) == (["RELIANCE"], [])
    stamps = [c["timestamp"].strftime("%H:%M") for c in f.candles("RELIANCE")]
    assert stamps[:3] == ["09:15", "09:20", "09:25"]
    # first live packet of the session must not wipe the seeded bars
    stamp = datetime(2026, 11, 11, 10, 18, 5, tzinfo=IST)
    f._on_data(None, {"token": "2885", "last_traded_price": 252000, "exchange_timestamp": int(stamp.timestamp() * 1000),
                      "volume_trade_for_the_day": 5000, "last_traded_quantity": 10})
    assert len(f.candles("RELIANCE")) >= 3


def test_incomplete_and_foreign_day_bars_are_ignored():
    api = Api([bar(10, 15, 2520), ["2026-11-10T09:15:00+05:30", 1, 2, 1, 2, 5]])
    assert fetch_today_candles(api, "2885", NOW, sleep=lambda s: None) == []


def test_retries_then_fails_soft():
    ok = Api([bar(9, 15, 2500)], fail_first=2)
    assert len(fetch_today_candles(ok, "2885", NOW, sleep=lambda s: None)) == 1
    dead = Api([], fail_first=99)
    assert fetch_today_candles(dead, "2885", NOW, sleep=lambda s: None) is None
    f = feed()
    assert backfill_today(f, dead, [{"symbol": "RELIANCE", "token": "2885"}], NOW, sleep=lambda s: None) == ([], ["RELIANCE"])


def test_nothing_to_fetch_before_first_bar_completes():
    early = datetime(2026, 11, 11, 9, 17, tzinfo=IST)
    assert backfill_today(feed(), Api([]), [{"symbol": "RELIANCE", "token": "2885"}], early, sleep=lambda s: None) == ([], [])
