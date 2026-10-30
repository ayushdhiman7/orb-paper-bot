from datetime import datetime
from zoneinfo import ZoneInfo

from angel_websocket import AngelWebSocketFeed

IST = ZoneInfo("Asia/Kolkata")


def packet(token="2885", minute=15, second=1, price=2500, volume=100, qty=10):
    stamp = datetime(2026, 10, 30, 9, minute, second, tzinfo=IST)
    return {
        "token": token,
        "last_traded_price": price * 100,
        "last_traded_timestamp": int(stamp.timestamp() * 1000),
        "exchange_timestamp": int(stamp.timestamp() * 1000),
        "volume_trade_for_the_day": volume,
        "last_traded_quantity": qty,
    }


def test_subscribes_all_configured_symbols_once_in_snap_quote_mode():
    class FakeSocket:
        def __init__(self, *_args, **_kwargs):
            self.subscription = None
        def subscribe(self, correlation, mode, tokens):
            self.subscription = (correlation, mode, tokens)

    feed = AngelWebSocketFeed(["RELIANCE.NS", "TCS.NS"], api=object(), websocket_factory=FakeSocket)
    # Exercise callback directly; no credentials or network are needed.
    feed.socket = FakeSocket()
    feed._on_open(None)
    correlation, mode, token_list = feed.socket.subscription
    assert correlation == "orbphase1"
    assert mode == 3
    assert token_list == [{"exchangeType": 1, "tokens": ["2885", "11536"]}]


def test_converts_paise_to_rupees_and_rejects_unknown_tokens():
    clock = [1000.0]
    feed = AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: clock[0])
    feed._on_data(None, packet(price=2512))
    feed._on_data(None, packet(token="99999", price=999))
    assert feed.last("RELIANCE.NS") == 2512.0


def test_stale_quotes_are_not_returned():
    clock = [1000.0]
    feed = AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: clock[0], max_stale_seconds=45)
    feed._on_data(None, packet())
    clock[0] += 46
    assert feed.last("RELIANCE.NS") is None


def test_builds_completed_five_minute_candles_and_volume_deltas():
    feed = AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: 1000.0)
    feed._on_data(None, packet(minute=15, second=1, price=100, volume=100, qty=100))
    feed._on_data(None, packet(minute=16, second=1, price=103, volume=130, qty=30))
    # Advancing into 09:20 finalizes the 09:15 candle.
    feed._on_data(None, packet(minute=20, second=1, price=102, volume=150, qty=20))
    rows = feed.candles("RELIANCE.NS")
    assert len(rows) == 1
    assert rows[0]["open"] == 100
    assert rows[0]["high"] == 103
    assert rows[0]["low"] == 100
    assert rows[0]["close"] == 103
    assert rows[0]["volume"] == 130


def test_forming_candle_is_not_exposed_as_completed():
    feed = AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: 1000.0)
    feed._on_data(None, packet(minute=15))
    assert feed.candles("RELIANCE.NS") == []


def test_session_rollover_clears_previous_session_bars():
    feed = AngelWebSocketFeed(["RELIANCE.NS"], clock=lambda: 1000.0)
    feed._on_data(None, packet(minute=15))
    feed._on_data(None, packet(minute=20))
    assert len(feed.candles("RELIANCE.NS")) == 1
    next_day = datetime(2026, 11, 2, 9, 15, 1, tzinfo=IST)
    p = packet(minute=15)
    p["last_traded_timestamp"] = int(next_day.timestamp() * 1000)
    p["exchange_timestamp"] = p["last_traded_timestamp"]
    feed._on_data(None, p)
    assert feed.candles("RELIANCE.NS") == []
