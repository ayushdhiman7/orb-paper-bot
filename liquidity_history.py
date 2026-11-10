"""Point-in-time liquidity metrics for the under-₹25 research universe."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

class LiquidityHistoryError(ValueError):
    """Historical turnover cannot be trusted for screening."""

def average_daily_traded_value(daily_candles, *, as_of: date, min_sessions: int = 20) -> Decimal:
    """Average close*volume in rupees from completed sessions strictly before as_of.

    Input candles must be daily OHLCV records with `ts`, `close`, and `volume`.
    Angel One daily candle prices are rupees (unlike its WebSocket binary prices,
    which are paise); do not divide these candle prices by 100.
    Duplicate dates and malformed/non-finite/negative values fail closed.
    """
    if min_sessions < 1:
        raise ValueError("min_sessions must be positive")
    by_day = {}
    for row in daily_candles:
        try:
            raw_date = row["ts"]
            if isinstance(raw_date, datetime):
                session = raw_date.date()
            elif isinstance(raw_date, date):
                session = raw_date
            else:
                session = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
            close = Decimal(str(row["close"]))
            volume = Decimal(str(row["volume"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise LiquidityHistoryError("Malformed daily candle") from None
        if not close.is_finite() or not volume.is_finite() or close <= 0 or volume < 0:
            raise LiquidityHistoryError("Invalid daily candle price or volume")
        if session >= as_of:
            continue
        if session in by_day:
            raise LiquidityHistoryError(f"Duplicate daily candle for {session.isoformat()}")
        by_day[session] = close * volume
    if len(by_day) < min_sessions:
        raise LiquidityHistoryError(f"Need {min_sessions} completed sessions; found {len(by_day)}")
    values = list(by_day.values())
    return sum(values, Decimal("0")) / Decimal(len(values))
