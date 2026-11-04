"""Balanced AI and deterministic position management for Nifty 50 paper positions."""
from __future__ import annotations

import json
from typing import Mapping, Sequence

from ai_manager import (
    MANAGEMENT_PROMPT,
    ManagementDecision,
    build_position_context,
    parse_management_response,
    validate_management_decision,
)


def build_review_prompt(positions: Sequence[Mapping], prices: Mapping[str, float], now) -> tuple[str, set[str]]:
    facts = []
    symbols = set()
    for pos in positions:
        symbol = str(pos["symbol"]).upper()
        price = float(prices[symbol])
        peak = float(pos.get("peak_price") or price)
        context = build_position_context(
            {
                "symbol": symbol, "side": pos["side"], "qty": pos["qty"],
                "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                "opened_at": pos["opened_at"],
            },
            price,
            peak,
        )
        facts.append({
            "symbol": context.symbol, "side": context.side, "quantity": context.quantity,
            "entry": context.entry, "current_price": context.current_price,
            "stop": context.stop, "target": context.target,
            "minutes_held": max(0, int((now - context.opened_at).total_seconds() // 60)),
            "peak_price": context.peak_price, "risk_per_share": context.risk_per_share,
            "completed_1m_candles": pos.get("candles_1m", [])[-12:],
        })
        symbols.add(symbol)
    prompt = (
        "Review every open paper position together. Return exactly one decision per symbol. "
        "Use only supplied facts. Allowed actions HOLD, MOVE_SL, LOCK_PROFIT, UPDATE_TARGET, EXIT. "
        "Never widen risk. For HOLD and EXIT new_stop/new_target must be null. "
        "Return JSON only: " + json.dumps({"decisions": [{
            "symbol": "SYMBOL", "action": "HOLD", "reason": "reason",
            "confidence": 0.0, "new_stop": None, "new_target": None
        }]}, separators=(",", ":")) + "\nPositions: " + json.dumps(facts, separators=(",", ":"), default=str)
    )
    return prompt, symbols


def parse_management_batch(raw: str, expected_symbols: set[str]) -> dict:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("position batch must be valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        raise ValueError("position batch must contain only decisions")
    rows = payload["decisions"]
    if not isinstance(rows, list) or len(rows) != len(expected_symbols):
        raise ValueError("position batch must cover every open position")
    seen = set()
    decisions = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("position decision must be an object")
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol or symbol not in expected_symbols or symbol in seen:
            raise ValueError("position batch has unknown or duplicate symbol")
        normalized = {key: row.get(key) for key in
                      ("action", "reason", "confidence", "new_stop", "new_target")}
        decision = parse_management_response(json.dumps(normalized))
        seen.add(symbol)
        decisions.append({"symbol": symbol, "decision": decision})
    if seen != expected_symbols:
        raise ValueError("position batch symbol coverage mismatch")
    return {"decisions": decisions, "reason": f"validated {len(decisions)} open-position decisions"}


def validate_management_batch(positions, prices, now, response, min_confidence=0.0):
    prompt, expected = build_review_prompt(positions, prices, now)
    if not isinstance(response, dict) or not isinstance(response.get("decisions"), list):
        return [], [{"reason": "ai_unavailable"}]
    by_symbol = {str(p["symbol"]).upper(): p for p in positions}
    approved, rejected = [], []
    if {row.get("symbol") for row in response["decisions"] if isinstance(row, dict)} != expected:
        return [], [{"reason": "incomplete_position_batch"}]
    for row in response["decisions"]:
        symbol = str(row["symbol"]).upper()
        decision = row["decision"]
        pos = by_symbol[symbol]
        context = build_position_context({
            "symbol": symbol, "side": pos["side"], "qty": pos["qty"],
            "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
            "opened_at": pos["opened_at"],
        }, prices[symbol], pos.get("peak_price") or prices[symbol])
        valid, reason = validate_management_decision(context, decision, min_confidence=min_confidence)
        if valid:
            approved.append({"symbol": symbol, "decision": decision})
        else:
            rejected.append({"symbol": symbol, "reason": reason})
    return approved, rejected


def protective_stop(position, price, *, one_r, one_half_r, two_r, protected_profit_r=0.5, atr=None, recent_lows=(), recent_highs=()):
    """Return a tighter stop at +1R/+1.5R/+2R; never increase initial risk."""
    entry = float(position["entry"])
    stop = float(position["stop"])
    direction = 1 if position["side"] == "BUY" else -1
    risk = abs(entry - stop)
    if risk <= 0:
        return stop, None
    current_r = (float(price) - entry) * direction / risk
    fee_per_share = max(0.0, float(position.get("round_trip_cost_per_share", 0.0)))
    proposed = stop
    trigger = None
    if current_r >= one_r:
        proposed = max(proposed, entry + direction * fee_per_share) if direction == 1 else min(proposed, entry - fee_per_share)
        trigger = "breakeven_1r"
    if current_r >= one_half_r:
        protected = entry + direction * (float(protected_profit_r) * risk + fee_per_share)
        proposed = max(proposed, protected) if direction == 1 else min(proposed, protected)
        trigger = "protect_0_5r"
    if current_r >= two_r:
        candidates = []
        if atr is not None and float(atr) > 0:
            candidates.append(float(price) - direction * float(atr))
        swings = recent_lows if direction == 1 else recent_highs
        if swings:
            candidates.append((max if direction == 1 else min)(float(v) for v in swings))
        if candidates:
            trailing = (max(candidates) if direction == 1 else min(candidates))
            proposed = max(proposed, trailing) if direction == 1 else min(proposed, trailing)
            trigger = "trail_2r"
    # Never widen risk and never set a stop through the current market price.
    if direction == 1:
        proposed = min(max(proposed, stop), float(price) - 0.0001)
    else:
        proposed = max(min(proposed, stop), float(price) + 0.0001)
    return round(proposed, 4), trigger
