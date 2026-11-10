"""Research-only NSE cash-equity universe and fail-closed under-₹25 filters.
This module does not connect to Angel One, place orders, or alter the Nifty 50 runtime.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Iterable, Mapping

class LowPriceUniverseError(ValueError):
    """Raised when the broker instrument master is ambiguous or malformed."""

@dataclass(frozen=True)
class LowPriceConfig:
    max_price: Decimal = Decimal("25.00")
    min_avg_daily_value: Decimal = Decimal("50000000")
    max_spread_pct: Decimal = Decimal("0.50")
    max_candidates: int = 100
    max_quote_age_seconds: int = 45

    def __post_init__(self):
        if self.max_price <= 0 or self.min_avg_daily_value < 0:
            raise ValueError("Price must be positive and turnover non-negative")
        if not (Decimal("0") < self.max_spread_pct <= Decimal("100")):
            raise ValueError("max_spread_pct must be in (0, 100]")
        if self.max_candidates < 1 or self.max_quote_age_seconds < 1:
            raise ValueError("candidate count and quote age must be positive")

def _decimal(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid {field}") from None
    if not result.is_finite():
        raise ValueError(f"Invalid {field}")
    return result

def parse_nse_cash_equities(master: Iterable[Mapping]) -> list[dict]:
    """Resolve unique Angel One NSE cash EQ rows; ignore F&O and other segments."""
    if not isinstance(master, (list, tuple)):
        raise LowPriceUniverseError("Instrument master must be a list")
    by_symbol, duplicates = {}, set()
    for row in master:
        if not isinstance(row, Mapping) or str(row.get("exch_seg", "")).strip().lower() not in {"nse", "nse_cm"}:
            continue
        trading_symbol = str(row.get("symbol", "")).strip().upper()
        if not trading_symbol.endswith("-EQ"):
            continue
        symbol, token = trading_symbol[:-3], str(row.get("token", "")).strip()
        if not symbol or not token.isdigit():
            continue
        record = {"symbol": symbol, "tradingsymbol": trading_symbol, "token": token, "exchange": "NSE", "tick_size": row.get("tick_size")}
        if symbol in by_symbol:
            duplicates.add(symbol)
        tick_size_raw = row.get("tick_size")
        try:
            tick_size_paise = Decimal(str(tick_size_raw))
            if not tick_size_paise.is_finite() or tick_size_paise <= 0:
                raise InvalidOperation
            record["tick_size_rupees"] = tick_size_paise / Decimal("100")
        except (InvalidOperation, TypeError, ValueError):
            record["tick_size_rupees"] = None
        by_symbol[symbol] = record
    if duplicates:
        raise LowPriceUniverseError("Ambiguous NSE cash tokens: " + ", ".join(sorted(duplicates)))
    return sorted(by_symbol.values(), key=lambda item: item["symbol"])

def select_under_25_candidates(instruments, quotes, avg_daily_values, *, now_epoch, config=LowPriceConfig()):
    """Fail-closed selector; quote requires price, bid, ask and received_at (Unix seconds)."""
    accepted = []
    for instrument in instruments:
        symbol = str(instrument.get("symbol", "")).strip().upper()
        quote = quotes.get(symbol)
        if not symbol or not isinstance(quote, Mapping):
            continue
        try:
            price = _decimal(quote.get("price"), "price")
            bid = _decimal(quote.get("bid"), "bid")
            ask = _decimal(quote.get("ask"), "ask")
            received = float(quote.get("received_at"))
            avg_value = _decimal(avg_daily_values.get(symbol), "average daily traded value")
            if not math.isfinite(received) or not math.isfinite(float(now_epoch)):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        if price <= 0 or bid <= 0 or ask < bid or avg_value < config.min_avg_daily_value:
            continue
        age = now_epoch - received
        if age < 0 or age > config.max_quote_age_seconds or price > config.max_price:
            continue
        midpoint = (bid + ask) / Decimal("2")
        spread_pct = ((ask - bid) / midpoint) * Decimal("100")
        if spread_pct > config.max_spread_pct:
            continue
        accepted.append({**dict(instrument), "price": float(price), "bid": float(bid), "ask": float(ask),
                         "spread_pct": float(spread_pct), "avg_daily_traded_value": float(avg_value), "quote_age_seconds": age})
    accepted.sort(key=lambda row: (-row["avg_daily_traded_value"], row["symbol"]))
    return accepted[:config.max_candidates]
