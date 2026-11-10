from datetime import date, timedelta
from decimal import Decimal

import pytest

from liquidity_history import (
    LiquidityHistoryError,
    SQLiteDailyCandleCache,
    average_daily_traded_value,
    load_average_daily_values,
)


def rows(n=20):
    start = date(2026, 10, 1)
    return [
        {"ts": (start + timedelta(days=i)).isoformat(), "close": "10.00", "volume": 1000}
        for i in range(n)
    ]


def test_average_turnover_uses_completed_sessions_only_and_rupee_prices():
    candles = rows() + [{"ts": "2026-11-10", "close": "999", "volume": 999999}]
    assert average_daily_traded_value(candles, as_of=date(2026, 11, 10)) == Decimal("10000")


def test_requires_minimum_history():
    with pytest.raises(LiquidityHistoryError, match="Need 20"):
        average_daily_traded_value(rows(19), as_of=date(2026, 11, 10))


def test_rejects_duplicate_dates_and_invalid_values():
    candles = rows()
    candles.append(candles[0])
    with pytest.raises(LiquidityHistoryError, match="Duplicate"):
        average_daily_traded_value(candles, as_of=date(2026, 11, 10))
    bad = rows()
    bad[0]["volume"] = "-1"
    with pytest.raises(LiquidityHistoryError, match="Invalid"):
        average_daily_traded_value(bad, as_of=date(2026, 11, 10))


class FakeAngelClient:
    def __init__(self, candles=None, error=None):
        self.result = candles if candles is not None else rows()
        self.error = error
        self.calls = []

    def candles(self, token, start, end, interval, exchange, use_cache):
        self.calls.append((token, start, end, interval, exchange, use_cache))
        if self.error:
            raise self.error
        return self.result


def test_history_loader_fetches_once_then_reuses_persistent_sqlite_cache(tmp_path):
    path = tmp_path / "liquidity.sqlite3"
    instrument = [{"symbol": "ABC", "token": "123"}]
    client = FakeAngelClient()
    cache = SQLiteDailyCandleCache(path)

    values, errors = load_average_daily_values(
        instrument, angel_client=client, as_of=date(2026, 11, 10),
        cache=cache, now_epoch=1000,
    )
    assert values == {"ABC": Decimal("10000")}
    assert errors == {}
    assert len(client.calls) == 1
    assert client.calls[0][3] == "ONE_DAY"
    assert client.calls[0][5] is False  # do not resurrect stale raw-candle cache entries

    # New cache object proves the result survives process restart.
    second_client = FakeAngelClient()
    values2, errors2 = load_average_daily_values(
        instrument, angel_client=second_client, as_of=date(2026, 11, 10),
        cache=SQLiteDailyCandleCache(path), now_epoch=1001,
    )
    assert values2 == values
    assert errors2 == {}
    assert second_client.calls == []


def test_history_loader_refreshes_expired_cache(tmp_path):
    path = tmp_path / "liquidity.sqlite3"
    instrument = [{"symbol": "ABC", "token": "123"}]
    first = FakeAngelClient()
    load_average_daily_values(
        instrument, angel_client=first, as_of=date(2026, 11, 10),
        cache=SQLiteDailyCandleCache(path), now_epoch=1000, cache_ttl_seconds=10,
    )

    refresh = FakeAngelClient()
    values, errors = load_average_daily_values(
        instrument, angel_client=refresh, as_of=date(2026, 11, 10),
        cache=SQLiteDailyCandleCache(path), now_epoch=1011, cache_ttl_seconds=10,
    )
    assert values == {"ABC": Decimal("10000")}
    assert errors == {}
    assert len(refresh.calls) == 1


def test_insufficient_history_is_not_cached_or_returned(tmp_path):
    client = FakeAngelClient(candles=rows(19))
    values, errors = load_average_daily_values(
        [{"symbol": "ABC", "token": "123"}], angel_client=client,
        as_of=date(2026, 11, 10), cache=SQLiteDailyCandleCache(tmp_path / "cache.sqlite3"),
        now_epoch=1000,
    )
    assert values == {}
    assert "Need 20" in errors["ABC"]


def test_rate_limit_stops_batch_without_requesting_remaining_symbols(tmp_path):
    from angel_data import AngelBlocked

    client = FakeAngelClient(error=AngelBlocked("access rate"))
    instruments = [
        {"symbol": "ABC", "token": "123"},
        {"symbol": "XYZ", "token": "456"},
    ]
    values, errors = load_average_daily_values(
        instruments, angel_client=client, as_of=date(2026, 11, 10),
        cache=SQLiteDailyCandleCache(tmp_path / "cache.sqlite3"), now_epoch=1000,
    )
    assert values == {}
    assert len(client.calls) == 1
    assert "access rate" in errors["ABC"]
