"""Point-in-time daily liquidity metrics and persistent cache for the under-₹25 research universe.

Historical daily candle prices are rupees (not paise). Only completed sessions
strictly before as_of contribute to the average. Cache entries are keyed by both
symbol and broker token so a changed instrument mapping cannot reuse old history.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_CACHE_PATH = os.getenv("LOW_PRICE_LIQUIDITY_CACHE", ".low_price_cache/liquidity.sqlite3")
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_LOOKBACK_CALENDAR_DAYS = 60


class LiquidityHistoryError(ValueError):
    """Historical turnover cannot be trusted for screening."""


class SQLiteDailyCandleCache:
    """Small local SQLite cache; writes are transactional and safe across restarts."""

    def __init__(self, path=DEFAULT_CACHE_PATH):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS daily_candle_cache (
                    symbol TEXT NOT NULL,
                    token TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    candles_json TEXT NOT NULL,
                    PRIMARY KEY (symbol, token, as_of)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_daily_candle_cache_fetched ON daily_candle_cache(fetched_at)")

    def get(self, symbol, token, *, as_of: date, now_epoch: float, max_age_seconds=DEFAULT_CACHE_TTL_SECONDS):
        with self._connect() as db:
            row = db.execute(
                "SELECT fetched_at, candles_json FROM daily_candle_cache WHERE symbol=? AND token=? AND as_of=?",
                (str(symbol).upper(), str(token), as_of.isoformat()),
            ).fetchone()
        if row is None:
            return None
        fetched_at, payload = row
        age = float(now_epoch) - float(fetched_at)
        if age < 0 or age > max_age_seconds:
            return None
        try:
            candles = json.loads(payload)
        except (TypeError, ValueError):
            raise LiquidityHistoryError(f"Corrupt cached daily candles for {symbol}") from None
        if not isinstance(candles, list):
            raise LiquidityHistoryError(f"Invalid cached daily candles for {symbol}")
        return candles

    def put(self, symbol, token, *, as_of: date, fetched_at: float, candles):
        try:
            payload = json.dumps(candles, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            raise LiquidityHistoryError(f"Daily candles for {symbol} are not JSON-safe") from None
        with self._connect() as db:
            db.execute(
                """INSERT INTO daily_candle_cache(symbol, token, as_of, fetched_at, candles_json)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, token, as_of) DO UPDATE SET
                     fetched_at=excluded.fetched_at, candles_json=excluded.candles_json""",
                (str(symbol).upper(), str(token), as_of.isoformat(), float(fetched_at), payload),
            )


def average_daily_traded_value(daily_candles, *, as_of: date, min_sessions: int = 20) -> Decimal:
    """Average close*volume in rupees from completed sessions strictly before as_of.

    Input candles must be daily OHLCV records with `ts`, `close`, and `volume`.
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


def load_average_daily_values(
    instruments,
    *,
    angel_client,
    as_of: date,
    cache=None,
    now_epoch=None,
    cache_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
    min_sessions=20,
    lookback_calendar_days=DEFAULT_LOOKBACK_CALENDAR_DAYS,
):
    """Load per-symbol 20-session average traded value with cache-first Angel One retrieval.

    Returns (values, errors). AngelBlocked stops the batch immediately to avoid
    repeated requests after a broker rate-limit response. A symbol without enough
    valid completed sessions is omitted, so the candidate selector fails closed.
    """
    if lookback_calendar_days < min_sessions:
        raise ValueError("lookback_calendar_days must allow at least min_sessions")
    if cache is None:
        cache = SQLiteDailyCandleCache()
    if now_epoch is None:
        now_epoch = datetime.now().timestamp()
    start = datetime.combine(as_of - timedelta(days=lookback_calendar_days), time.min)
    end = datetime.combine(as_of, time.min)
    values, errors = {}, {}
    for instrument in instruments:
        symbol = str(instrument.get("symbol", "")).strip().upper()
        token = str(instrument.get("token", "")).strip()
        if not symbol or not token:
            errors[symbol or "<unknown>"] = "missing symbol or Angel One token"
            continue
        try:
            candles = cache.get(
                symbol, token, as_of=as_of, now_epoch=now_epoch,
                max_age_seconds=cache_ttl_seconds,
            )
            if candles is None:
                candles = angel_client.candles(
                    token, start, end, interval="ONE_DAY", exchange="NSE", use_cache=False
                )
                # Validate before persisting: partial or malformed history never becomes trusted cache.
                value = average_daily_traded_value(candles, as_of=as_of, min_sessions=min_sessions)
                cache.put(symbol, token, as_of=as_of, fetched_at=now_epoch, candles=candles)
            else:
                value = average_daily_traded_value(candles, as_of=as_of, min_sessions=min_sessions)
            values[symbol] = value
        except Exception as exc:
            # Broker rate-limit means stop this batch immediately; never hammer remaining symbols.
            from angel_data import AngelBlocked
            if isinstance(exc, AngelBlocked):
                errors[symbol] = str(exc)
                break
            errors[symbol] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return values, errors
