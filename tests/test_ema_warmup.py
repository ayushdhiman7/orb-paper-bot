from indicators import calculate_indicators


def bars(n, start=100.0, step=0.5):
    return [{"high": start + i * step + 1, "low": start + i * step - 1, "close": start + i * step, "volume": 100} for i in range(n)]


def test_without_warmup_trend_is_unknown_early_in_session():
    assert calculate_indicators(bars(6)).trend == "insufficient_data"


def test_warmup_makes_trend_available_but_vwap_atr_stay_session_only():
    today = bars(6, start=120)
    snap = calculate_indicators(today, warmup_candles=bars(40, start=100))
    assert snap.trend in {"bullish", "bearish", "neutral"} and snap.ema20 is not None
    base = calculate_indicators(today)
    assert snap.vwap == base.vwap and snap.atr14 == base.atr14


def test_uptrend_with_warmup_is_bullish():
    snap = calculate_indicators(bars(6, start=120), warmup_candles=bars(40, start=100))
    assert snap.trend == "bullish"
