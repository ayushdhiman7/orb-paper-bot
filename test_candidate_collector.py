from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from candidate_collector import CandidateCollectionError, collect_candidates

IST = ZoneInfo("Asia/Kolkata")
TODAY = datetime(2026, 11, 3, 13, 0, tzinfo=IST)


def universe():
    return [
        {"symbol": f"STOCK{i:02d}", "token": str(1000 + i)}
        for i in range(50)
    ]


def bars(symbol="STOCK00", trend="bullish"):
    rows = []
    start = datetime(2026, 11, 3, 9, 15, tzinfo=IST)
    # A complete 09:15-09:30 opening range followed by enough 5m history.
    for i in range(40):
        stamp = start + timedelta(minutes=5 * i)
        if i < 3:
            base = 100.0 + i * 0.1
            high, low, close = base + 1, base - 1, base
        elif trend == "bullish":
            close = 102 + i * 0.25
            high, low = close + 0.3, close - 0.3
        else:
            close = 120 - i * 0.25
            high, low = close + 0.3, close - 0.3
        rows.append({
            "timestamp": stamp, "open": close, "high": high, "low": low,
            "close": close, "volume": 1000,
        })
    return rows


class FakeFeed:
    def __init__(self, quote_by_symbol=None, candles_by_symbol=None):
        self.quote_by_symbol = quote_by_symbol or {}
        self.candles_by_symbol = candles_by_symbol or {}

    def last(self, symbol):
        return self.quote_by_symbol.get(symbol)

    def candles(self, symbol):
        return self.candles_by_symbol.get(symbol, [])


def test_collects_aligned_breakout_candidates_as_one_batch():
    u = universe()
    feed = FakeFeed(
        {"STOCK00": 115.0},
        {"STOCK00": bars()},
    )
    result = collect_candidates(u, feed, TODAY, {"STOCK00": {"score": 0.7}})
    assert len(result) == 1
    assert result[0]["symbol"] == "STOCK00"
    assert result[0]["side"] == "BUY"
    assert result[0]["sentiment"] == {"score": 0.7}


def test_skips_missing_quote_incomplete_opening_range_and_neutral_price():
    u = universe()
    feed = FakeFeed(
        {"STOCK00": 115.0, "STOCK02": 101.0},
        {"STOCK00": bars()[:2], "STOCK01": bars(), "STOCK02": bars()},
    )
    result = collect_candidates(u, feed, TODAY)
    assert [row["symbol"] for row in result] == []


def test_requires_exactly_50_unique_instruments():
    with pytest.raises(CandidateCollectionError, match="exactly 50"):
        collect_candidates(universe()[:-1], FakeFeed(), TODAY)


def test_excludes_already_traded_symbols_and_out_of_window_scans():
    feed = FakeFeed({"STOCK00": 104.0}, {"STOCK00": bars()})
    assert collect_candidates(universe(), feed, TODAY, excluded_symbols={"STOCK00"}) == []
    before_opening_range = datetime(2026, 11, 3, 9, 29, tzinfo=IST)
    assert collect_candidates(universe(), feed, before_opening_range) == []


def test_sell_breakout_requires_bearish_trend_and_below_vwap():
    feed = FakeFeed({"STOCK00": 90.0}, {"STOCK00": bars(trend="bearish")})
    result = collect_candidates(universe(), feed, TODAY)
    assert len(result) == 1
    assert result[0]["side"] == "SELL"
