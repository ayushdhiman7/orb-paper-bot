"""Pure batch-entry decision parsing and deterministic paper-risk validation.

This module does not fetch market data, call Gemini, persist state, or place orders.
Callers supply a complete candidate batch and portfolio snapshot. Invalid or
missing AI output is rejected as a whole; no partial batch is eligible.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


DECISIONS = {"BUY", "SELL", "SKIP"}


@dataclass(frozen=True)
class EntryCandidate:
    symbol: str
    signal_side: str
    current_price: float
    opening_range_high: float
    opening_range_low: float
    indicators: Mapping[str, Any]
    sentiment: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PortfolioLimits:
    capital: float
    available_cash: float
    risk_per_trade_pct: float
    max_positions: int
    open_positions: int
    max_trades_per_day: int
    trades_today: int
    daily_loss_cap_pct: float
    day_pnl: float
    min_confidence: float = 0.0


@dataclass(frozen=True)
class ValidatedEntry:
    symbol: str
    side: str
    confidence: float
    reason: str
    stop: float
    target: float
    rank: int
    quantity: int
    risk_amount: float


def _finite_positive(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return number


def parse_batch_response(raw: str, expected_symbols: set[str]) -> list[dict]:
    """Require exactly one well-formed decision for every requested symbol."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty batch response")
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("batch response must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        raise ValueError("batch response must contain only a decisions array")
    items = payload["decisions"]
    if not isinstance(items, list) or len(items) != len(expected_symbols):
        raise ValueError("batch must contain exactly one decision per candidate")

    seen: set[str] = set()
    parsed: list[dict] = []
    ranks: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each decision must be an object")
        symbol = str(item.get("symbol", "")).strip().upper()
        decision = str(item.get("decision", "")).strip().upper()
        if symbol not in expected_symbols or symbol in seen:
            raise ValueError("unknown or duplicate candidate symbol")
        if decision not in DECISIONS:
            raise ValueError(f"unsupported decision for {symbol}")
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid confidence for {symbol}") from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f"invalid confidence for {symbol}")
        reason = str(item.get("reason", "")).strip()
        if not reason or len(reason) > 300:
            raise ValueError(f"reason for {symbol} must contain 1-300 characters")
        rank_value = item.get("rank")
        if isinstance(rank_value, bool) or not isinstance(rank_value, int) or rank_value < 1:
            raise ValueError(f"rank for {symbol} must be a positive integer")
        if rank_value in ranks:
            raise ValueError("decision ranks must be unique")
        ranks.add(rank_value)

        stop = item.get("stop")
        target = item.get("target")
        if decision == "SKIP":
            if stop is not None or target is not None:
                raise ValueError(f"SKIP for {symbol} must not propose stop or target")
        else:
            stop = _finite_positive(stop, f"{symbol}.stop")
            target = _finite_positive(target, f"{symbol}.target")
        seen.add(symbol)
        parsed.append({
            "symbol": symbol, "decision": decision, "confidence": confidence,
            "reason": reason, "stop": stop, "target": target, "rank": rank_value,
        })
    if seen != {str(s).upper() for s in expected_symbols}:
        raise ValueError("batch symbol coverage mismatch")
    return sorted(parsed, key=lambda item: item["rank"])


def validate_batch(
    candidates: Sequence[EntryCandidate],
    decisions: Sequence[Mapping[str, Any]],
    limits: PortfolioLimits,
) -> tuple[list[ValidatedEntry], list[dict]]:
    """Validate all proposed entries; return accepted entries and explicit rejections.

    Candidates are already eligible ORB breakouts. An AI BUY/SELL must agree with
    that breakout direction. Position slots, daily limits, daily loss cap, confidence,
    stop/target geometry, cash and per-trade risk are enforced deterministically.
    """
    if not candidates:
        return [], []
    if limits.capital <= 0 or limits.available_cash < 0:
        raise ValueError("invalid portfolio capital or available cash")
    if not 0 < limits.risk_per_trade_pct <= 100:
        raise ValueError("risk_per_trade_pct must be in (0, 100]")
    if not 0 <= limits.min_confidence <= 1:
        raise ValueError("min_confidence must be in [0, 1]")
    if limits.max_positions < 1 or limits.open_positions < 0:
        raise ValueError("invalid position limits")

    by_symbol = {c.symbol.upper(): c for c in candidates}
    if len(by_symbol) != len(candidates):
        raise ValueError("candidate symbols must be unique")
    by_decision = {str(d.get("symbol", "")).upper(): d for d in decisions}
    if len(by_decision) != len(decisions) or set(by_decision) != set(by_symbol):
        raise ValueError("decisions must cover each candidate exactly once")

    rejections: list[dict] = []
    accepted: list[ValidatedEntry] = []
    free_slots = max(0, limits.max_positions - limits.open_positions)
    remaining_trades = max(0, limits.max_trades_per_day - limits.trades_today)
    remaining_cash = limits.available_cash
    risk_budget = limits.capital * limits.risk_per_trade_pct / 100
    loss_cap_hit = limits.day_pnl <= -limits.capital * limits.daily_loss_cap_pct / 100

    for decision in sorted(decisions, key=lambda d: int(d.get("rank", 0))):
        symbol = str(decision["symbol"]).upper()
        candidate = by_symbol[symbol]
        side = str(decision["decision"]).upper()
        confidence = float(decision["confidence"])
        reason = str(decision["reason"])
        if side == "SKIP":
            rejections.append({"symbol": symbol, "verdict": "SKIP", "reason": "ai_skipped"})
            continue

        rejection = None
        if loss_cap_hit:
            rejection = "daily_loss_cap_reached"
        elif confidence < limits.min_confidence:
            rejection = "confidence_below_threshold"
        elif free_slots <= 0:
            rejection = "max_open_positions_reached"
        elif remaining_trades <= 0:
            rejection = "max_trades_per_day_reached"
        elif side != candidate.signal_side.upper():
            rejection = "side_conflicts_with_breakout_signal"

        price = _finite_positive(candidate.current_price, f"{symbol}.current_price")
        stop = _finite_positive(decision.get("stop"), f"{symbol}.stop")
        target = _finite_positive(decision.get("target"), f"{symbol}.target")
        if rejection is None:
            if side == "BUY" and not (stop < price < target):
                rejection = "invalid_buy_stop_target_geometry"
            elif side == "SELL" and not (target < price < stop):
                rejection = "invalid_sell_stop_target_geometry"

        if rejection is None:
            per_share_risk = abs(price - stop)
            if per_share_risk <= 0 or per_share_risk * 1 > risk_budget:
                rejection = "per_share_risk_exceeds_trade_budget"
        quantity = 0
        risk_amount = 0.0
        if rejection is None:
            quantity_by_risk = int(risk_budget // per_share_risk)
            quantity_by_cash = int(remaining_cash // price)
            quantity = min(quantity_by_risk, quantity_by_cash)
            if quantity < 1:
                rejection = "insufficient_cash_or_risk_budget"
            else:
                risk_amount = quantity * per_share_risk
        if rejection:
            rejections.append({"symbol": symbol, "verdict": "REJECTED", "reason": rejection})
            continue

        accepted.append(ValidatedEntry(
            symbol=symbol, side=side, confidence=confidence, reason=reason,
            stop=stop, target=target, rank=int(decision["rank"]),
            quantity=quantity, risk_amount=round(risk_amount, 2),
        ))
        free_slots -= 1
        remaining_trades -= 1
        remaining_cash -= quantity * price
    return accepted, rejections
