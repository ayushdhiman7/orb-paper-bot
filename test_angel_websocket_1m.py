from datetime import datetime
from zoneinfo import ZoneInfo

from angel_websocket import AngelWebSocketFeed

IST = ZoneInfo("Asia/Kolkata")


def _packet(minute, second, price):
    stamp = datetime(2026, 10, 30, 9, minute, second, tzinfo=IST)
    return {
        "token": "2885",
        "last_traded_price": price * 100,
        "last_traded_timestamp": int(stamp.timestamp() * 1000),
        "exchange_timestamp": int(stamp.timestamp() * 1000),
        "volume_trade_for_the_day": 100,
        "last_traded_quantity": 1,
    }


def test_builds_completed_one_minute_candles_for_ai_reviews():
    feed = AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: 1000.0)
    feed._on_data(None, _packet(15, 1, 100))
    feed._on_data(None, _packet(15, 30, 102))
    assert feed.candles_1m("RELIANCE.NS") == []
    feed._on_data(None, _packet(16, 1, 101))
    rows = feed.candles_1m("RELIANCE.NS")
    assert len(rows) == 1
    assert rows[0]["open"] == 100
    assert rows[0]["high"] == 102
    assert rows[0]["low"] == 100
    assert rows[0]["close"] == 102
