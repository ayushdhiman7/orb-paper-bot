"""Deterministic indicators for completed NSE 5-minute candles.

The caller must supply only completed candles from the current NSE session,
ordered oldest to newest. No network calls or third-party dependencies.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping


@dataclass(frozen=True)
class IndicatorSnapshot:
    close: float
    ema20: float | None
    previous_ema20: float | None
    trend: str
    vwap: float | None
    atr14: float | None
    extension_atr: float | None


def _number(value, field):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"candle {field} must be numeric") from exc
    if not isfinite(result):
        raise ValueError(f"candle {field} must be finite")
    return result


def _validate(candles: Iterable[Mapping]):
    rows = list(candles)
    parsed = []
    for index, row in enumerate(rows):
        try:
            high = _number(row["high"], "high")
            low = _number(row["low"], "low")
            close = _number(row["close"], "close")
            volume = _number(row["volume"], "volume")
        except (KeyError, TypeError) as exc:
            raise ValueError(f"candle {index} is missing required OHLCV fields") from exc
        if high < low or not (low <= close <= high):
            raise ValueError(f"candle {index} has inconsistent OHLC values")
        if volume < 0:
            raise ValueError(f"candle {index} volume cannot be negative")
        parsed.append({"high": high, "low": low, "close": close, "volume": volume})
    return parsed


def ema(values, period):
    """EMA seeded with the SMA of the first period values."""
    if period < 1:
        raise ValueError("period must be >= 1")
    values = [_number(v, "value") for v in values]
    if len(values) < period:
        return None
    current = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
    return current


def atr(candles, period=14):
    """Wilder ATR over completed candles; requires period + 1 candles."""
    rows = _validate(candles)
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(rows) < period + 1:
        return None
    true_ranges = []
    previous_close = rows[0]["close"]
    for row in rows[1:]:
        true_ranges.append(max(
            row["high"] - row["low"],
            abs(row["high"] - previous_close),
            abs(row["low"] - previous_close),
        ))
        previous_close = row["close"]
    current = sum(true_ranges[:period]) / period
    for value in true_ranges[period:]:
        current = ((current * (period - 1)) + value) / period
    return current


def session_vwap(candles):
    """Cumulative session VWAP using typical price * candle volume / volume."""
    rows = _validate(candles)
    total_volume = 0.0
    total_value = 0.0
    for row in rows:
        if row["volume"] == 0:
            continue
        typical = (row["high"] + row["low"] + row["close"]) / 3.0
        total_value += typical * row["volume"]
        total_volume += row["volume"]
    return total_value / total_volume if total_volume else None


def calculate_indicators(candles, ema_period=20, atr_period=14):
    """Return latest 5m indicators. At least two EMA values are needed for trend."""
    rows = _validate(candles)
    if not rows:
        raise ValueError("at least one completed candle is required")
    closes = [row["close"] for row in rows]
    latest_ema = ema(closes, ema_period)
    previous_ema = ema(closes[:-1], ema_period) if len(closes) > ema_period else None
    close = closes[-1]
    if latest_ema is None or previous_ema is None:
        trend = "insufficient_data"
    elif close > latest_ema and latest_ema > previous_ema:
        trend = "bullish"
    elif close < latest_ema and latest_ema < previous_ema:
        trend = "bearish"
    else:
        trend = "neutral"
    current_vwap = session_vwap(rows)
    current_atr = atr(rows, atr_period)
    extension = abs(close - current_vwap) / current_atr if current_vwap is not None and current_atr else None
    return IndicatorSnapshot(
        close=close,
        ema20=latest_ema,
        previous_ema20=previous_ema,
        trend=trend,
        vwap=current_vwap,
        atr14=current_atr,
        extension_atr=extension,
    )


def entry_alignment(side, snapshot):
    """Return whether trend and VWAP agree with a proposed BUY/SELL direction."""
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if snapshot.vwap is None or snapshot.trend in {"insufficient_data", "neutral"}:
        return False
    if side == "BUY":
        return snapshot.trend == "bullish" and snapshot.close > snapshot.vwap
    return snapshot.trend == "bearish" and snapshot.close < snapshot.vwap
