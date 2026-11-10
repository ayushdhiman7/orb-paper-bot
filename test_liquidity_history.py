from datetime import date, timedelta
from decimal import Decimal
import pytest
from liquidity_history import LiquidityHistoryError, average_daily_traded_value

def rows(n=20):
    start = date(2026, 1, 1)
    return [{"ts": (start + timedelta(days=i)).isoformat(), "close": "10.00", "volume": 1000} for i in range(n)]

def test_average_turnover_uses_completed_sessions_only_and_rupee_prices():
    candles = rows() + [{"ts":"2026-11-10","close":"999","volume":999999}]
    assert average_daily_traded_value(candles, as_of=date(2026,11,10)) == Decimal("10000")

def test_requires_minimum_history():
    with pytest.raises(LiquidityHistoryError, match="Need 20"):
        average_daily_traded_value(rows(19), as_of=date(2026,11,10))

def test_rejects_duplicate_dates_and_invalid_values():
    candles=rows(); candles.append(candles[0])
    with pytest.raises(LiquidityHistoryError, match="Duplicate"):
        average_daily_traded_value(candles, as_of=date(2026,11,10))
    bad=rows(); bad[0]["volume"]="-1"
    with pytest.raises(LiquidityHistoryError, match="Invalid"):
        average_daily_traded_value(bad, as_of=date(2026,11,10))
