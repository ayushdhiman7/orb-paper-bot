"""Deterministic, paper-only Nifty 50 ORB candidate collection.

This module reads an already validated universe and an injected live feed. It
never calls an AI service, persists trades, or submits broker orders.
"""
from __future__ import annotations

from datetime import date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from indicators import calculate_indicators, entry_alignment

IST = ZoneInfo("Asia/Kolkata")
OPENING_RANGE_START = time(9, 15)
OPENING_RANGE_END = time(9, 30)
LAST_ENTRY_TIME = time(14, 30)


class CandidateCollectionError(RuntimeError):
    """Candidate collection cannot safely evaluate the supplied inputs."""


def _timestamp(value):
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CandidateCollectionError("candle timestamp is invalid") from exc
    else:
        raise CandidateCollectionError("candle timestamp must be a datetime or ISO string")
    if stamp.tzinfo is None:
        raise CandidateCollectionError("candle timestamp must include a timezone")
    return stamp.astimezone(IST)


def _validate_universe(universe):
    if not isinstance(universe, list) or len(universe) != 50:
        raise CandidateCollectionError("candidate scan requires exactly 50 validated instruments")
    symbols, tokens = set(), set()
    for item in universe:
        if not isinstance(item, dict):
            raise CandidateCollectionError("universe instrument must be an object")
        symbol, token = str(item.get("symbol", "")).strip().upper(), str(item.get("token", "")).strip()
        if not symbol or not token.isdigit():
            raise CandidateCollectionError("universe contains an invalid symbol or token")
        if symbol in symbols or token in tokens:
            raise CandidateCollectionError("universe contains duplicate symbols or tokens")
        symbols.add(symbol)
        tokens.add(token)


def _opening_range(candles, session_date):
    opening = []
    for candle in candles:
        stamp = _timestamp(candle.get("timestamp"))
        if stamp.date() == session_date and OPENING_RANGE_START <= stamp.time().replace(tzinfo=None) < OPENING_RANGE_END:
            opening.append(candle)
    opening.sort(key=lambda row: _timestamp(row["timestamp"]))
    # Three completed 5-minute bars are required for the full 09:15-09:30 range.
    if len(opening) != 3:
        return None
    stamps = [_timestamp(row["timestamp"]).time().replace(tzinfo=None) for row in opening]
    if stamps != [time(9, 15), time(9, 20), time(9, 25)]:
        return None
    highs = [float(row["high"]) for row in opening]
    lows = [float(row["low"]) for row in opening]
    if not all(isfinite(value) and value > 0 for value in highs + lows):
        return None
    return max(highs), min(lows)


def collect_candidates(universe, feed, now, sentiment_by_symbol=None, excluded_symbols=None):
    """Return all aligned live ORB candidates, ordered by symbol.

    feed must expose quote(symbol, now) with price, event_time and received_at, plus candles(symbol). A stale/missing quote,
    incomplete opening range, insufficient indicator history, neutral trend,
    or VWAP disagreement excludes the symbol. Sentiment is optional context only.
    """
    _validate_universe(universe)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise CandidateCollectionError("now must be a timezone-aware datetime")
    now = now.astimezone(IST)
    if now.time().replace(tzinfo=None) < OPENING_RANGE_END or now.time().replace(tzinfo=None) > LAST_ENTRY_TIME:
        return []
    sentiment_by_symbol = sentiment_by_symbol or {}
    excluded = {str(s).strip().upper() for s in (excluded_symbols or set())}
    candidates = []

    for instrument in universe:
        symbol = instrument["symbol"].strip().upper()
        if symbol in excluded:
            continue
        try:
            # Require timestamped evidence from the connected WebSocket adapter.
            quote = feed.quote(symbol, now)
            if not isinstance(quote, dict):
                continue
            event_time = _timestamp(quote.get("event_time"))
            received_at = quote.get("received_at")
            if isinstance(received_at, bool) or not isinstance(received_at, (int, float)) or not isfinite(received_at):
                continue
            event_age = now.timestamp() - event_time.timestamp()
            receive_age = now.timestamp() - float(received_at)
            if event_age < -5 or event_age > 45 or receive_age < 0 or receive_age > 45:
                continue
            price = float(quote.get("price"))
            if not isfinite(price) or price <= 0:
                continue
            candles = feed.candles(symbol)
            if not isinstance(candles, list) or not candles:
                continue
            # Ignore future or prior-session bars; only completed bars are supplied by the feed.
            session_candles = [
                row for row in candles
                if _timestamp(row.get("timestamp")).date() == now.date()
                and _timestamp(row.get("timestamp")) < now
            ]
            if not session_candles:
                continue
            session_candles.sort(key=lambda row: _timestamp(row["timestamp"]))
            opening = _opening_range(session_candles, now.date())
            if opening is None:
                continue
            range_high, range_low = opening
            if price > range_high:
                side = "BUY"
            elif price < range_low:
                side = "SELL"
            else:
                continue
            snapshot = calculate_indicators(session_candles, ema_period=20, atr_period=14)
            if not entry_alignment(side, snapshot):
                continue
            candidates.append({
                "symbol": symbol,
                "side": side,
                "price": round(price, 4),
                "quote_evidence": {"event_time": event_time.isoformat(), "received_at": float(received_at)},
                "opening_range_high": round(range_high, 4),
                "opening_range_low": round(range_low, 4),
                "indicators": {
                    "close": round(snapshot.close, 4),
                    "ema20": round(snapshot.ema20, 4) if snapshot.ema20 is not None else None,
                    "previous_ema20": round(snapshot.previous_ema20, 4) if snapshot.previous_ema20 is not None else None,
                    "trend": snapshot.trend,
                    "vwap": round(snapshot.vwap, 4) if snapshot.vwap is not None else None,
                    "atr14": round(snapshot.atr14, 4) if snapshot.atr14 is not None else None,
                    "extension_atr": round(snapshot.extension_atr, 4) if snapshot.extension_atr is not None else None,
                },
                "sentiment": sentiment_by_symbol.get(symbol),
            })
        except (CandidateCollectionError, KeyError, TypeError, ValueError, OverflowError):
            # One malformed symbol/feed packet must not crash the batch or create a candidate.
            continue

    return sorted(candidates, key=lambda item: item["symbol"])
