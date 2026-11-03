"""Final deterministic paper-entry sizing using the bot's actual fill and cost model.

This module produces an execution plan only. It does not persist trades, mutate
portfolio state, call a broker, or submit orders.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from batch_entry import EntryCandidate, PortfolioLimits, ValidatedEntry


@dataclass(frozen=True)
class PaperExecutionPlan:
    symbol: str
    side: str
    quantity: int
    market_price: float
    entry_fill: float
    stop: float
    target: float
    entry_fee: float
    risk_amount: float
    confidence: float
    reason: str
    rank: int


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} is invalid")
    return result


def _floor_quantity(budget, per_share):
    if per_share <= 0:
        return 0
    return max(0, int(math.floor(budget / per_share)))


def recompute_paper_execution(
    entry: ValidatedEntry,
    candidate: EntryCandidate,
    limits: PortfolioLimits,
    *,
    slippage_pct: float,
    cost_pct: float,
) -> PaperExecutionPlan | None:
    """Recheck current limits and recompute size after adverse entry slippage and fees."""
    slip = _number(slippage_pct, "slippage_pct")
    cost = _number(cost_pct, "cost_pct")
    if not 0 <= slip <= 100 or not 0 <= cost <= 100:
        raise ValueError("slippage_pct and cost_pct must be within 0..100")

    symbol = str(candidate.symbol).strip().upper()
    if not symbol or symbol != str(entry.symbol).strip().upper():
        raise ValueError("candidate and validated entry symbols do not match")
    side = str(entry.side).strip().upper()
    if side not in {"BUY", "SELL"} or side != str(candidate.signal_side).strip().upper():
        return None

    # The portfolio snapshot is intentionally checked again at execution time.
    if limits.open_positions >= limits.max_positions:
        return None
    if limits.trades_today >= limits.max_trades_per_day:
        return None
    if limits.day_pnl <= -(limits.capital * limits.daily_loss_cap_pct / 100):
        return None
    if entry.confidence < limits.min_confidence:
        return None

    price = _number(candidate.current_price, "current_price", positive=True)
    stop = _number(entry.stop, "stop", positive=True)
    target = _number(entry.target, "target", positive=True)
    capital = _number(limits.capital, "capital", positive=True)
    cash = _number(limits.available_cash, "available_cash")
    risk_pct = _number(limits.risk_per_trade_pct, "risk_per_trade_pct", positive=True)
    if cash < 0 or not 0 < risk_pct <= 100:
        return None

    direction = 1 if side == "BUY" else -1
    entry_fill = price * (1 + direction * slip / 100)
    if side == "BUY" and not stop < entry_fill < target:
        return None
    if side == "SELL" and not target < entry_fill < stop:
        return None

    per_share_risk = abs(entry_fill - stop)
    risk_budget = capital * risk_pct / 100
    quantity_by_risk = _floor_quantity(risk_budget, per_share_risk)
    # Existing fee_for_notional charges half the configured round-trip cost on entry.
    entry_cost_multiplier = 1 + cost / 2 / 100
    quantity_by_cash = _floor_quantity(cash, entry_fill * entry_cost_multiplier)
    quantity = min(quantity_by_risk, quantity_by_cash)
    if quantity < 1:
        return None

    entry_fee = quantity * entry_fill * (cost / 2 / 100)
    return PaperExecutionPlan(
        symbol=symbol, side=side, quantity=quantity,
        market_price=price, entry_fill=entry_fill, stop=stop, target=target,
        entry_fee=entry_fee, risk_amount=quantity * per_share_risk,
        confidence=entry.confidence, reason=entry.reason, rank=entry.rank,
    )
