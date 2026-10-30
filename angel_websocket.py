"""Angel One SmartAPI WebSocket V2 feed and completed 5-minute candle builder.

This module is intentionally not wired into bot.py yet. Validate SNAP_QUOTE access,
packet freshness and reconnect behaviour with the real account before switching the
paper bot away from its current feed.
"""
import os
import threading
import time
from collections import deque
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from angel_feed import NAMES, TOKENS, _env, base_name, silence_sdk_logging

IST = ZoneInfo("Asia/Kolkata")
NSE_OPEN = dtime(9, 15)
NSE_CLOSE = dtime(15, 30)
SNAP_QUOTE_MODE = 3
NSE_CM = 1
CORRELATION_ID = "orbphase1"


class AngelWebSocketFeed:
    def __init__(self, symbols, api=None, websocket_factory=None, clock=time.time,
                 max_stale_seconds=45):
        self.symbols = [base_name(s) for s in symbols if base_name(s) in TOKENS]
        self.token_to_symbol = {TOKENS[s]: s for s in self.symbols}
        self._api = api
        self._websocket_factory = websocket_factory
        self._clock = clock
        self.max_stale_seconds = max_stale_seconds
        self.socket = None
        self.connected = False
        self.last_error = None
        self.latest = {}
        self._last_day_volume = {}
        self._session_dates = {}
        self._forming = {}
        self._completed = {s: deque(maxlen=200) for s in self.symbols}
        self._lock = threading.RLock()
        self._thread = None

    def _login(self):
        if self._api is not None:
            return self._api
        missing = [kind for kind in NAMES if not _env(kind)]
        if missing:
            raise RuntimeError("missing Angel One credentials: " + ", ".join(missing))
        try:
            import pyotp
            from SmartApi import SmartConnect
        except ImportError as exc:
            raise RuntimeError("install requirements-angelone-test.txt for Angel One WebSocket support") from exc
        silence_sdk_logging()
        api = SmartConnect(api_key=_env("key"))
        response = api.generateSession(_env("client"), _env("pin"), pyotp.TOTP(_env("totp")).now())
        if not isinstance(response, dict) or not response.get("status"):
            raise RuntimeError("Angel One login failed")
        data = response.get("data") or {}
        auth_token = data.get("jwtToken")
        feed_token = data.get("feedToken")
        client_code = _env("client")
        if not auth_token or not feed_token:
            raise RuntimeError("Angel One login response did not include WebSocket tokens")
        return api, auth_token, feed_token, client_code

    def start(self):
        """Start the SDK's blocking WebSocket loop on a daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
            login = self._login()
            if isinstance(login, tuple):
                api, auth_token, feed_token, client_code = login
            else:
                raise RuntimeError("invalid injected login response")
            self._api = api
            self.socket = (self._websocket_factory or SmartWebSocketV2)(
                auth_token, _env("key"), client_code, feed_token,
                max_retry_attempt=3, retry_strategy=1, retry_delay=5,
                retry_multiplier=2, retry_duration=60,
            )
            self.socket.on_open = self._on_open
            self.socket.on_data = self._on_data
            self.socket.on_error = self._on_error
            self.socket.on_close = self._on_close
            self._thread = threading.Thread(target=self.socket.connect, name="angel-ws", daemon=True)
            self._thread.start()
        except Exception as exc:
            self.last_error = f"WebSocket start failed: {type(exc).__name__}: {str(exc)[:100]}"
            raise

    def _on_open(self, _wsapp):
        token_list = [{"exchangeType": NSE_CM, "tokens": list(self.token_to_symbol)}]
        self.socket.subscribe(CORRELATION_ID, SNAP_QUOTE_MODE, token_list)
        self.connected = True
        self.last_error = None

    def _on_error(self, _wsapp, error):
        self.connected = False
        self.last_error = f"WebSocket error: {type(error).__name__}: {str(error)[:100]}"

    def _on_close(self, _wsapp):
        self.connected = False

    @staticmethod
    def _timestamp(packet):
        raw = packet.get("exchange_timestamp") or packet.get("last_traded_timestamp")
        if raw is None:
            raise ValueError("quote packet has no exchange timestamp")
        value = float(raw)
        # SmartAPI supplies epoch milliseconds in its binary packet.
        return datetime.fromtimestamp(value / 1000.0, tz=IST)

    def _on_data(self, _wsapp, packet):
        try:
            token = str(packet.get("token", ""))
            symbol = self.token_to_symbol.get(token)
            if symbol is None:
                return
            price = float(packet["last_traded_price"]) / 100.0
            if price <= 0:
                return
            event_time = self._timestamp(packet)
            received_at = self._clock()
            quote = {
                "symbol": symbol,
                "price": price,
                "event_time": event_time,
                "received_at": received_at,
                "volume_trade_for_the_day": int(packet.get("volume_trade_for_the_day") or 0),
                "last_traded_quantity": int(packet.get("last_traded_quantity") or 0),
            }
            with self._lock:
                self.latest[symbol] = quote
                self._update_candle(symbol, quote)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            self.last_error = f"invalid WebSocket packet: {type(exc).__name__}"

    def _update_candle(self, symbol, quote):
        event_time = quote["event_time"]
        clock_time = event_time.time()
        if not (NSE_OPEN <= clock_time < NSE_CLOSE):
            return
        session_date = event_time.date()
        if self._session_dates.get(symbol) != session_date:
            self._session_dates[symbol] = session_date
            self._last_day_volume.pop(symbol, None)
            self._forming.pop(symbol, None)
            self._completed[symbol].clear()

        minute = event_time.hour * 60 + event_time.minute
        bucket_minute = minute - (minute % 5)
        bucket = event_time.replace(hour=bucket_minute // 60, minute=bucket_minute % 60,
                                     second=0, microsecond=0)
        current = self._forming.get(symbol)
        if current and bucket > current["timestamp"]:
            self._completed[symbol].append(current.copy())
            current = None
        if current is None:
            current = {
                "timestamp": bucket,
                "open": quote["price"],
                "high": quote["price"],
                "low": quote["price"],
                "close": quote["price"],
                "volume": 0.0,
            }
            self._forming[symbol] = current
        current["high"] = max(current["high"], quote["price"])
        current["low"] = min(current["low"], quote["price"])
        current["close"] = quote["price"]

        cumulative = quote["volume_trade_for_the_day"]
        previous = self._last_day_volume.get(symbol)
        if previous is None:
            delta = quote["last_traded_quantity"]
        elif cumulative >= previous:
            delta = cumulative - previous
        else:
            # Exchange volume reset within a session: fail closed on this packet's volume.
            delta = 0
        self._last_day_volume[symbol] = cumulative
        current["volume"] += max(0, delta)

    def last(self, symbol, now=None):
        """Fresh LTP in rupees, or None when disconnected/stale."""
        name = base_name(symbol)
        with self._lock:
            quote = self.latest.get(name)
            if quote is None:
                return None
            age = self._clock() - quote["received_at"]
            if age < 0 or age > self.max_stale_seconds:
                return None
            return quote["price"]

    def candles(self, symbol):
        """Completed current-session 5m OHLCV candles; excludes the forming candle."""
        with self._lock:
            return [row.copy() for row in self._completed.get(base_name(symbol), ())]

    def stop(self):
        self.connected = False
        if self.socket is not None:
            self.socket.close_connection()
