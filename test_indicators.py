import pytest

from indicators import atr, calculate_indicators, ema, entry_alignment, session_vwap


def bars(closes, volumes=None, spread=2.0):
    volumes = volumes or [100.0] * len(closes)
    return [
        {"high": c + spread / 2, "low": c - spread / 2, "close": c, "volume": v}
        for c, v in zip(closes, volumes)
    ]


def test_ema_uses_sma_seed_and_standard_smoothing():
    assert ema([10, 11, 12, 13], 3) == pytest.approx(12.0)
    assert ema([10, 11, 12, 13, 14], 3) == pytest.approx(13.0)


def test_ema_requires_full_period():
    assert ema([1, 2], 3) is None


def test_vwap_is_volume_weighted_typical_price():
    rows = [
        {"high": 12, "low": 8, "close": 10, "volume": 100},
        {"high": 22, "low": 18, "close": 20, "volume": 300},
    ]
    expected = ((10 * 100) + (20 * 300)) / 400
    assert session_vwap(rows) == pytest.approx(expected)


def test_vwap_returns_none_when_no_volume():
    assert session_vwap(bars([10, 11], [0, 0])) is None


def test_atr_uses_true_range_and_wilder_smoothing():
    rows = [
        {"high": 11, "low": 9, "close": 10, "volume": 1},
        {"high": 13, "low": 10, "close": 12, "volume": 1},
        {"high": 14, "low": 11, "close": 13, "volume": 1},
        {"high": 15, "low": 12, "close": 14, "volume": 1},
    ]
    assert atr(rows, 2) == pytest.approx(3.0)


def test_atr_requires_period_plus_one_candles():
    assert atr(bars([10, 11, 12]), 3) is None


def test_bullish_trend_and_vwap_alignment():
    closes = list(range(100, 125))
    snapshot = calculate_indicators(bars(closes), ema_period=5, atr_period=3)
    assert snapshot.trend == "bullish"
    assert entry_alignment("BUY", snapshot) is True
    assert entry_alignment("SELL", snapshot) is False


def test_bearish_trend_and_vwap_alignment():
    closes = list(range(125, 100, -1))
    snapshot = calculate_indicators(bars(closes), ema_period=5, atr_period=3)
    assert snapshot.trend == "bearish"
    assert entry_alignment("SELL", snapshot) is True
    assert entry_alignment("BUY", snapshot) is False


def test_neutral_and_insufficient_data_fail_closed():
    flat = calculate_indicators(bars([100] * 10), ema_period=5, atr_period=3)
    assert flat.trend == "neutral"
    assert entry_alignment("BUY", flat) is False
    short = calculate_indicators(bars([100, 101, 102]), ema_period=5, atr_period=3)
    assert short.trend == "insufficient_data"
    assert entry_alignment("BUY", short) is False


def test_invalid_ohlcv_is_rejected():
    with pytest.raises(ValueError, match="inconsistent OHLC"):
        session_vwap([{"high": 9, "low": 10, "close": 10, "volume": 1}])


def test_invalid_side_is_rejected():
    snapshot = calculate_indicators(bars([100, 101, 102, 103]), ema_period=2, atr_period=2)
    with pytest.raises(ValueError, match="side must be"):
        entry_alignment("HOLD", snapshot)
