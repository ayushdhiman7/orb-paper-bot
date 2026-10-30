"""Phase 2 AI position-management contracts and deterministic safety validation.

This module is deliberately side-effect free: it validates AI proposals but does not
submit orders, mutate Supabase rows, or alter the running paper bot.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any


ACTIONS = {"HOLD", "MOVE_SL", "LOCK_PROFIT", "UPDATE_TARGET", "EXIT"}
ENTRY_DECISIONS = {"BUY", "SELL", "SKIP"}


@dataclass(frozen=True)
class PositionContext:
    symbol: str
    side: str
    quantity: int
    entry: float
    current_price: float
    stop: float
    target: float
    opened_at: datetime
    peak_price: float
    risk_per_share: float


@dataclass(frozen=True)
class ManagementDecision:
    action: str
    reason: str
    confidence: float
    new_stop: float | None = None
    new_target: float | None = None


def _positive_number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def parse_management_response(raw: str) -> ManagementDecision:
    """Parse strict JSON from Gemini. Invalid/missing fields raise ValueError."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty AI response")
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(match.group(0) if match else raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("AI response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("AI response must be a JSON object")
    action = str(data.get("action", "")).strip().upper()
    if action not in ACTIONS:
        raise ValueError("unsupported management action")
    reason = str(data.get("reason", "")).strip()
    if not reason or len(reason) > 300:
        raise ValueError("reason must contain 1-300 characters")
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    stop = data.get("new_stop")
    target = data.get("new_target")
    if action in {"MOVE_SL", "LOCK_PROFIT"}:
        stop = _positive_number(stop, "new_stop")
    elif stop is not None:
        stop = _positive_number(stop, "new_stop")
    if action == "UPDATE_TARGET":
        target = _positive_number(target, "new_target")
    elif target is not None:
        target = _positive_number(target, "new_target")
    return ManagementDecision(action, reason, confidence, stop, target)


def validate_management_decision(
    context: PositionContext,
    decision: ManagementDecision,
    *,
    min_confidence: float = 0.65,
    square_off_time: str = "15:15",
) -> tuple[bool, str]:
    """Validate an AI proposal against hard deterministic position protections."""
    if context.side not in {"BUY", "SELL"}:
        return False, "invalid_position_side"
    if context.quantity <= 0 or min(context.entry, context.current_price, context.stop, context.target) <= 0:
        return False, "invalid_position_values"
    if decision.confidence < min_confidence:
        return False, "confidence_below_threshold"
    if decision.action == "HOLD":
        return True, "accepted"
    if decision.action == "EXIT":
        return True, "accepted"
    buy = context.side == "BUY"
    if decision.action in {"MOVE_SL", "LOCK_PROFIT"}:
        proposed = decision.new_stop
        if proposed is None:
            return False, "missing_new_stop"
        # Stop may only move in the protective direction; it can never widen risk.
        if buy and proposed <= context.stop:
            return False, "stop_would_widen_risk"
        if not buy and proposed >= context.stop:
            return False, "stop_would_widen_risk"
        # Never place a stop through/at the current mark.
        if buy and proposed >= context.current_price:
            return False, "stop_not_below_current_price"
        if not buy and proposed <= context.current_price:
            return False, "stop_not_above_current_price"
        if decision.action == "LOCK_PROFIT":
            if buy and proposed <= context.entry:
                return False, "profit_lock_must_be_above_entry"
            if not buy and proposed >= context.entry:
                return False, "profit_lock_must_be_below_entry"
        return True, "accepted"
    if decision.action == "UPDATE_TARGET":
        proposed = decision.new_target
        if proposed is None:
            return False, "missing_new_target"
        if buy and proposed <= context.target:
            return False, "target_must_move_further_in_profit_direction"
        if not buy and proposed >= context.target:
            return False, "target_must_move_further_in_profit_direction"
        if buy and proposed <= context.current_price:
            return False, "target_must_be_above_current_price"
        if not buy and proposed >= context.current_price:
            return False, "target_must_be_below_current_price"
        return True, "accepted"
    return False, "unsupported_action"


def build_position_context(position: dict, current_price: float, peak_price: float) -> PositionContext:
    """Create a typed AI context from normalized paper-position fields."""
    entry = _positive_number(position.get("entry"), "entry")
    stop = _positive_number(position.get("stop"), "stop")
    return PositionContext(
        symbol=str(position.get("symbol", "")).upper(),
        side=str(position.get("side", "")).upper(),
        quantity=int(position.get("qty", 0)),
        entry=entry,
        current_price=_positive_number(current_price, "current_price"),
        stop=stop,
        target=_positive_number(position.get("target"), "target"),
        opened_at=position["opened_at"],
        peak_price=_positive_number(peak_price, "peak_price"),
        risk_per_share=abs(entry - stop),
    )


MANAGEMENT_PROMPT = """You manage an existing NSE intraday PAPER position.
Return exactly one JSON object with keys: action, reason, confidence, new_stop, new_target.
Allowed actions: HOLD, MOVE_SL, LOCK_PROFIT, UPDATE_TARGET, EXIT.
Use only the supplied facts. Never invent news, prices, indicators or events.
Prefer HOLD when the setup remains valid. Never propose widening the stop.
MOVE_SL and LOCK_PROFIT require new_stop. UPDATE_TARGET requires new_target.
For HOLD and EXIT use null for new_stop and new_target.
confidence must be a number from 0 to 1; reason must be concise.
The deterministic risk engine may reject your proposal. You do not execute orders.
Position facts:
{context}"""


ENTRY_BATCH_PROMPT = """Review all eligible Nifty 50 paper-trading candidates together.
For every candidate return one decision: BUY, SELL, or SKIP, plus confidence (0..1),
reason, and proposed stop and target. Rank accepted candidates best-first.
Do not invent facts. Consider supplied technical and sentiment evidence only.
Never exceed the supplied max_positions, risk_per_trade_pct or daily limits.
Return JSON only: {{"decisions":[{{"symbol":"...","decision":"BUY|SELL|SKIP",
"confidence":0.0,"reason":"...","stop":null,"target":null,"rank":1}}]}}.
The deterministic risk engine validates every candidate before any paper entry.
Candidates:
{candidates}"""


class GeminiQuota:
    """Thread-safe rolling 5-RPM and IST-day request limiter with optional persisted state."""

    def __init__(self, daily_limit=100, per_minute_limit=5, clock=time.time, state=None):
        import threading
        self.daily_limit = int(daily_limit)
        self.per_minute_limit = int(per_minute_limit)
        if self.daily_limit < 1 or self.per_minute_limit < 1:
            raise ValueError("quota limits must be positive")
        self._clock = clock
        self._state = state if state is not None else {"day": None, "count": 0, "recent": []}
        self._lock = threading.Lock()

    def reserve(self, now: datetime) -> tuple[bool, str]:
        epoch = self._clock()
        day = now.date().isoformat()
        with self._lock:
            if self._state.get("day") != day:
                self._state.update({"day": day, "count": 0, "recent": []})
            recent = [float(ts) for ts in self._state.get("recent", []) if epoch - float(ts) < 60]
            if self._state.get("count", 0) >= self.daily_limit:
                self._state["recent"] = recent
                return False, "daily_quota_exhausted"
            if len(recent) >= self.per_minute_limit:
                self._state["recent"] = recent
                return False, "per_minute_quota_exhausted"
            recent.append(epoch)
            self._state["recent"] = recent
            self._state["count"] = int(self._state.get("count", 0)) + 1
            return True, "reserved"

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)


def parse_entry_batch_response(raw: str, expected_symbols: set[str]) -> list[dict]:
    """Validate the batch envelope and reject duplicate/unknown candidate symbols."""
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("entry batch response is not valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise ValueError("entry batch response must contain decisions array")
    seen = set()
    output = []
    for item in data["decisions"]:
        if not isinstance(item, dict):
            raise ValueError("each decision must be an object")
        symbol = str(item.get("symbol", "")).upper()
        decision = str(item.get("decision", "")).upper()
        if symbol not in expected_symbols or symbol in seen:
            raise ValueError("unknown or duplicate candidate symbol")
        if decision not in ENTRY_DECISIONS:
            raise ValueError("invalid entry decision")
        confidence = float(item.get("confidence"))
        if not 0 <= confidence <= 1:
            raise ValueError("entry confidence must be between 0 and 1")
        reason = str(item.get("reason", "")).strip()
        if not reason or len(reason) > 300:
            raise ValueError("entry reason must contain 1-300 characters")
        seen.add(symbol)
        output.append({**item, "symbol": symbol, "decision": decision,
                       "confidence": confidence, "reason": reason})
    if seen != expected_symbols:
        raise ValueError("AI must return exactly one decision for every candidate")
    return output
